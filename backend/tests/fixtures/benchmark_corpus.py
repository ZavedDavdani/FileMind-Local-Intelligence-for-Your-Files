"""Canonical Benchmark Corpus Generator for Retrieval Evaluation.

Combines realistic structural fixtures and adversarial structural fixtures
into a unified, deterministic local corpus for retrieval benchmarking.
"""

import os
import sys
import hashlib
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

CORPUS_VERSION = "benchmark-corpus-v1"


def generate_adversarial_corpus(target_dir: str):
    """Generates structural adversarial text, markdown, and code test documents."""
    os.makedirs(target_dir, exist_ok=True)

    # 1. Deeply nested headings
    nested_md = target_dir + "/nested_headings.md"
    with open(nested_md, "w", encoding="utf-8") as f:
        f.write("# Architecture Overview\n\nHigh level architecture document.\n\n")
        f.write("## Subsystem A\n\nDetails of subsystem A.\n\n")
        f.write("### Component A.1\n\nDeep component details.\n\n")
        f.write("#### Micro-service A.1.1\n\nSpecific microservice constraints and configs.\n\n")

    # 2. Mixed content with code snippets and tables
    mixed_md = target_dir + "/mixed_content.md"
    with open(mixed_md, "w", encoding="utf-8") as f:
        f.write("# Database Tuning Guide\n\n")
        f.write("SQLite Write-Ahead Logging settings for high concurrency workloads.\n\n")
        f.write("```sql\nPRAGMA journal_mode = WAL;\nPRAGMA synchronous = NORMAL;\n```\n\n")
        f.write("| Parameter | Default | Recommended |\n| --- | --- | --- |\n| Cache Size | 2000 | 64000 |\n| Busy Timeout | 5000 | 30000 |\n\n")

    # 3. Dense technical document
    dense_txt = target_dir + "/dense_spec.txt"
    with open(dense_txt, "w", encoding="utf-8") as f:
        f.write("FileMind Core Invariants Specification:\n")
        f.write("1. All files are indexed locally with exact provenance coordinates.\n")
        f.write("2. No cloud dependencies or outbound network calls for core search.\n")
        f.write("3. SQLite FTS5 BM25 combined with sqlite-vec embeddings via Reciprocal Rank Fusion.\n")


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
