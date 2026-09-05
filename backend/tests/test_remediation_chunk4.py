"""
Regression test suite for Remediation Chunk 4 (Findings 19-24).
- Finding 21: Vectorized NumPy L2 normalization in EmbeddingEngine.
- Finding 22: Batch chunk queries via get_chunks_by_files in ChunkRepository and synthesis.
- Finding 23 & 24: Precompiled regex and clean boundary snippet generation in generate_real_snippet.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from app.retrieval.embeddings import EmbeddingEngine
from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.retrieval.hybrid import generate_real_snippet
from app.ai.knowledge_synthesis import KnowledgeSynthesisService


def test_finding21_vectorized_embedding_normalization():
    """EmbeddingEngine should perform vectorized NumPy L2 normalization safely without loop overhead or NaNs."""
    engine = EmbeddingEngine()
    engine._model = MagicMock()

    # Provide raw non-unit vectors
    raw_embeddings = [
        [3.0, 4.0] + [0.0] * 382,
        [1.0, 2.0, 2.0] + [0.0] * 381,
        [0.0] * 384,  # Zero vector
    ]
    engine._model.embed.return_value = iter(raw_embeddings)

    normalized = engine.embed_texts(["text1", "text2", "text3"])
    assert len(normalized) == 3

    # Vector 1 norm should be 1.0 (3/5, 4/5)
    v1 = np.array(normalized[0])
    assert pytest.approx(np.linalg.norm(v1), 1e-5) == 1.0
    assert pytest.approx(v1[0], 1e-5) == 0.6
    assert pytest.approx(v1[1], 1e-5) == 0.8

    # Vector 2 norm should be 1.0 (1/3, 2/3, 2/3)
    v2 = np.array(normalized[1])
    assert pytest.approx(np.linalg.norm(v2), 1e-5) == 1.0
    assert pytest.approx(v2[0], 1e-5) == 1.0 / 3.0

    # Vector 3 (zero vector) should not produce NaN or Inf
    v3 = np.array(normalized[2])
    assert not np.isnan(v3).any()
    assert not np.isinf(v3).any()


def test_finding22_batch_chunk_queries(tmp_path):
    """ChunkRepository.get_chunks_by_files must batch retrieve all chunks across multiple files in a single query."""
    db_file = tmp_path / "test_chunks_batch.db"
    mgr = DatabaseManager(db_path=db_file, pooled=False)

    with mgr.session() as conn:
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                file_id TEXT,
                source_file TEXT,
                source_path TEXT,
                page INTEGER,
                section TEXT,
                h1_parent TEXT,
                h2_parent TEXT,
                line_start INTEGER,
                line_end INTEGER,
                char_start INTEGER,
                char_end INTEGER,
                content_hash TEXT,
                chunk_index INTEGER,
                parser_name TEXT,
                parser_version TEXT,
                chunker_version TEXT,
                content TEXT,
                content_type TEXT,
                token_count INTEGER,
                metadata_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        repo = Repository(conn)

        # Insert chunks for 3 files
        for fid, count in [("f1", 4), ("f2", 3), ("f3", 2)]:
            chunks_to_insert = [
                {
                    "chunk_id": f"{fid}_c{i}",
                    "content": f"Content for {fid} chunk {i}",
                    "chunk_index": i,
                }
                for i in range(count)
            ]
            repo.replace_file_chunks(fid, chunks_to_insert)

        # Batch retrieve
        batch_res = repo.get_chunks_by_files(["f1", "f2", "f3", "f_nonexistent"])
        assert len(batch_res["f1"]) == 4
        assert len(batch_res["f2"]) == 3
        assert len(batch_res["f3"]) == 2
        assert len(batch_res["f_nonexistent"]) == 0
        assert batch_res["f1"][0]["chunk_id"] == "f1_c0"
        assert batch_res["f2"][1]["content"] == "Content for f2 chunk 1"


def test_finding23_and_24_generate_real_snippet_precompiled_boundaries():
    """generate_real_snippet should match word boundaries without interior-substring false matches and format cleanly."""
    content = "The category classification system uses cat detectors to index documents with feline topics."

    # 'cat' should match the whole word 'cat', not the prefix in 'category'
    snippet = generate_real_snippet(content, ["cat"], max_chars=60)
    assert "cat detectors" in snippet

    # Query with punctuation or regex special chars should be escaped safely
    regex_content = "Configuration has parameter max_depth=10 and threshold [0.95] for filtering."
    snippet_regex = generate_real_snippet(regex_content, ["[0.95]", "max_depth=10"], max_chars=80)
    assert "[0.95]" in snippet_regex

    # Long text truncation with ellipsis
    long_content = "Intro word. " + ("Middle sentence. " * 30) + "TargetKeyword found here. " + ("End sentence. " * 30)
    snippet_long = generate_real_snippet(long_content, ["TargetKeyword"], max_chars=60)
    assert "TargetKeyword" in snippet_long
    assert snippet_long.startswith("...") or snippet_long.endswith("...")
