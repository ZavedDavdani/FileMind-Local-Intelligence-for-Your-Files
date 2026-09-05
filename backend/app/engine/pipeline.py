"""Indexing pipeline orchestration for parsing, quality assessment, chunking, and embedding."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Dict, List, Optional

from app.core.config import MAX_FILE_SIZE_BYTES
from app.engine.hasher import compute_file_sha256
from app.intelligence.chunker.hierarchical import CHUNKER_VERSION, HierarchicalChunker
from app.intelligence.detector import detect_file_format
from app.intelligence.parsers.base import (
    CorruptedDocumentError,
    DocumentParserError,
    EncryptedDocumentError,
    UnsupportedFormatError,
)
from app.intelligence.parsers.registry import ParserRegistry, default_parser_registry

logger = logging.getLogger("FileMind.Engine.Pipeline")


@dataclass
class IndexingPipelineResult:
    """Outcome of processing a single file through the indexing pipeline."""

    file_id: str
    job_id: str
    status: str  # "INDEXED" | "SKIPPED" | "FAILED"
    sha256: Optional[str] = None
    chunks: List[Any] = field(default_factory=list)
    vector_records: List[Dict[str, Any]] = field(default_factory=list)
    dimension: int = 384
    indexing_error: Optional[str] = None
    vector_write_skipped_reason: Optional[str] = None
    permanent_failure: bool = False
    is_unchanged_bypass: bool = False


class IndexingPipeline:
    """Orchestrates file format detection, hashing, document parsing, quality gating,

    hierarchical chunking, and embedding generation outside database transactions.
    """

    def __init__(
        self,
        chunker: Optional[HierarchicalChunker] = None,
        parser_registry: Optional[ParserRegistry] = None,
        embedding_engine: Optional[Any] = None,
    ):
        self.chunker = chunker or HierarchicalChunker()
        self.parser_registry = parser_registry or default_parser_registry
        self._embedding_engine = embedding_engine

    @property
    def embedding_engine(self):
        if self._embedding_engine is not None:
            return self._embedding_engine
        from app.retrieval.embeddings import default_embedding_engine
        return default_embedding_engine

    def execute(
        self,
        file_path: str,
        file_id: str,
        job_id: str,
        existing_file_rec: Optional[Dict[str, Any]] = None,
        existing_chunk_vers: Optional[Dict[str, str]] = None,
    ) -> IndexingPipelineResult:
        """Executes the full pipeline for a single file on disk."""

        # 0. Check Max File Size Ingestion Guard
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0

        if file_size > MAX_FILE_SIZE_BYTES:
            err_msg = f"File size ({file_size} bytes) exceeds limit ({MAX_FILE_SIZE_BYTES} bytes)"
            logger.info("File %s exceeds max size limit: %d bytes", file_path, file_size)
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="SKIPPED",
                indexing_error=err_msg,
            )

        # 1. Compute SHA-256 Hash
        sha256_hash, hash_error = compute_file_sha256(file_path)
        if hash_error:
            logger.warning("Job %s for file %s failed hashing: %s", job_id, file_path, hash_error)
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="FAILED",
                indexing_error=hash_error,
                permanent_failure=False,
            )

        # 2. Check if file format is supported for Document Intelligence
        mime_type, _ = detect_file_format(file_path)
        parser = self.parser_registry.get_parser_for_file(file_path, mime_type)

        if not parser:
            ext = os.path.splitext(file_path)[1].lower()
            diag_reason = f"Unsupported file format '{ext or mime_type}' (no parser registered)"
            logger.info("File %s skipped: %s", file_path, diag_reason)
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="SKIPPED",
                sha256=sha256_hash,
                indexing_error=diag_reason,
            )

        # 3. Strict Integrity verification: unchanged hash and versions bypass
        if (
            existing_file_rec
            and existing_file_rec.get("sha256") == sha256_hash
            and existing_chunk_vers
        ):
            if (
                existing_chunk_vers.get("parser_version") == parser.parser_version
                and existing_chunk_vers.get("chunker_version") == self.chunker.chunker_version
            ):
                logger.info("File %s integrity verified (unchanged SHA-256 and versions)", file_path)
                return IndexingPipelineResult(
                    file_id=file_id,
                    job_id=job_id,
                    status="INDEXED",
                    sha256=sha256_hash,
                    is_unchanged_bypass=True,
                )

        # 4. Document Parsing & Hierarchical Chunking
        try:
            doc = parser.parse(file_path, file_id=file_id, mime_type=mime_type)

            # Quality Gate & Vectorization Boundary Check
            if hasattr(doc, "quality_assessment") and doc.quality_assessment:
                qa = doc.quality_assessment
                if qa.status == "REQUIRES_OCR":
                    logger.info("File %s requires OCR: %s", file_path, qa.reason_codes)
                    return IndexingPipelineResult(
                        file_id=file_id,
                        job_id=job_id,
                        status="SKIPPED",
                        sha256=sha256_hash,
                        indexing_error=qa.to_json(),
                    )

            chunks = self.chunker.chunk_document(doc)

            # Compute vector embeddings outside the database write transaction
            vec_records: List[Dict[str, Any]] = []
            dimension = 384
            vector_write_skipped_reason: Optional[str] = None

            if chunks:
                try:
                    dimension = self.embedding_engine.dimension
                    texts = [c.content if hasattr(c, "content") else c["content"] for c in chunks]
                    chunk_ids = [c.chunk_id if hasattr(c, "chunk_id") else c["chunk_id"] for c in chunks]
                    vectors = self.embedding_engine.embed_texts(texts)
                    if not vectors or len(vectors) != len(chunks):
                        raise RuntimeError(
                            f"Embedding count mismatch: expected {len(chunks)}, got {len(vectors) if vectors else 0}"
                        )
                    vec_records = [
                        {"chunk_id": cid, "file_id": file_id, "embedding": vec}
                        for cid, vec in zip(chunk_ids, vectors)
                    ]
                except Exception as vec_exc:
                    logger.warning(
                        "Vector embedding generation failed for file %s: %s", file_id, str(vec_exc)
                    )
                    vector_write_skipped_reason = f"Vector embedding generation warning: {str(vec_exc)}"

            parse_warning_msg = None
            if (
                hasattr(doc, "quality_assessment")
                and doc.quality_assessment
                and doc.quality_assessment.status == "PARSE_WARNING"
            ):
                parse_warning_msg = doc.quality_assessment.to_json()

            final_error = parse_warning_msg
            if vector_write_skipped_reason:
                final_error = (
                    f"{parse_warning_msg}; {vector_write_skipped_reason}"
                    if parse_warning_msg
                    else vector_write_skipped_reason
                )

            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="INDEXED",
                sha256=sha256_hash,
                chunks=chunks,
                vector_records=vec_records,
                dimension=dimension,
                indexing_error=final_error,
                vector_write_skipped_reason=vector_write_skipped_reason,
            )

        except EncryptedDocumentError as enc_exc:
            logger.info("File %s is encrypted/password protected: %s", file_path, str(enc_exc))
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="SKIPPED",
                sha256=sha256_hash,
                indexing_error=f"Encrypted/Password Protected: {str(enc_exc)}",
            )

        except CorruptedDocumentError as corp_exc:
            logger.warning("File %s is corrupted: %s", file_path, str(corp_exc))
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="FAILED",
                indexing_error=str(corp_exc),
                permanent_failure=True,
            )

        except Exception as parse_exc:
            logger.error("Parser failed on %s: %s", file_path, str(parse_exc), exc_info=True)
            return IndexingPipelineResult(
                file_id=file_id,
                job_id=job_id,
                status="FAILED",
                indexing_error=f"Parse failure: {str(parse_exc)}",
                permanent_failure=True,
            )
