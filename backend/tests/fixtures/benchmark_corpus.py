"""Canonical Benchmark Corpus Generator for Phase 3 Retrieval Evaluation.

Corpus Version: phase3-benchmark-corpus-v1
Combines the realistic structural fixtures (phase2-structural-corpus-v1) and
adversarial structural fixtures (phase2-adversarial-corpus-v2) into a unified,
deterministic local corpus for retrieval benchmarking.
"""

import os
import sys
from typing import Dict, Any, List

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.detector import detect_file_format
from app.intelligence.parsers.registry import default_parser_registry
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from tests.fixtures.realistic_corpus import generate_realistic_structural_corpus
from tests.freeze_pass.measure_real_document_structure import generate_adversarial_corpus

CORPUS_VERSION = "phase3-benchmark-corpus-v1"


def setup_benchmark_corpus(target_dir: str, db_path: str) -> Dict[str, Any]:
    """
    Sets up the full benchmark corpus in target_dir, applies migrations to db_path,
    ingests all documents, generates chunks, and returns the corpus metadata.
    """
    os.makedirs(target_dir, exist_ok=True)
    db = DatabaseManager(db_path)

    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(target_dir)
        folder_id = folder["folder_id"]

    # 1. Generate structural corpus fixtures
    c1_dir = os.path.join(target_dir, "structural")
    c2_dir = os.path.join(target_dir, "adversarial")
    generate_realistic_structural_corpus(c1_dir)
    generate_adversarial_corpus(c2_dir)

    chunker = HierarchicalChunker()
    files_indexed = []
    chunks_indexed = []
    total_bytes = 0

    import hashlib

    for root, _, filenames in sorted(os.walk(target_dir)):
        for fname in sorted(filenames):
            if fname.endswith((".db", ".db-wal", ".db-shm")):
                continue
            abs_path = os.path.normpath(os.path.join(root, fname))
            rel_path = os.path.normpath(os.path.relpath(abs_path, target_dir))
            clean_rel = rel_path.replace("\\", "/")
            det_fid = "file_" + hashlib.sha256(clean_rel.encode("utf-8")).hexdigest()[:16]
            size = os.path.getsize(abs_path)
            total_bytes += size
            _, ext = os.path.splitext(fname)
            mime, _ = detect_file_format(abs_path)
            parser = default_parser_registry.get_parser_for_file(abs_path, mime)

            with db.session() as conn:
                repo = Repository(conn)
                frec = repo.upsert_file(
                    folder_id=folder_id,
                    path=abs_path,
                    relative_path=rel_path,
                    filename=fname,
                    extension=ext.lower(),
                    size_bytes=size,
                    modified_at="2026-08-30T10:00:00Z",
                    sha256="benchmark_sha256_" + fname,
                    file_id=det_fid,
                )
                fid = frec["file_id"]
                files_indexed.append(frec)

                if parser:
                    doc = parser.parse(abs_path, file_id=fid, mime_type=mime)
                    chunks = chunker.chunk_document(doc)
                    repo.replace_file_chunks(fid, chunks)
                    for c in chunks:
                        c_dict = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else c.__dict__)
                        chunks_indexed.append(c_dict)

    # Precompute and index dense embeddings for all chunks into sqlite-vec
    if chunks_indexed:
        from app.retrieval.embeddings import default_embedding_engine
        from app.retrieval.vector_store import SqliteVecStore
        texts = [c["content"] for c in chunks_indexed]
        vectors = default_embedding_engine.embed_texts(texts, batch_size=16)
        with db.session() as conn:
            vec_store = SqliteVecStore(conn, dimension=default_embedding_engine.dimension)
            records = [
                {"chunk_id": c["chunk_id"], "file_id": c["file_id"], "embedding": v}
                for c, v in zip(chunks_indexed, vectors)
            ]
            vec_store.upsert_vectors(records)
            vec_store.set_index_metadata(
                provider="fastembed",
                model_name=default_embedding_engine.model_name,
                model_version=getattr(default_embedding_engine, "model_version", "1.0.0"),
                dimension=default_embedding_engine.dimension,
            )

    return {
        "corpus_version": CORPUS_VERSION,
        "folder_id": folder_id,
        "total_files": len(files_indexed),
        "total_chunks": len(chunks_indexed),
        "total_bytes": total_bytes,
        "files": files_indexed,
        "chunks": chunks_indexed,
    }
