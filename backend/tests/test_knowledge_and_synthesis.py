"""
Tests for Cross-File Intelligence & Synthesis Engine.
"""

import pytest
from unittest.mock import MagicMock

from app.ai.generation import GroundedGenerationService
from app.ai.knowledge_synthesis import KnowledgeSynthesisService
from app.ai.ollama_provider import OllamaProvider, OllamaResponse
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository


@pytest.fixture
def knowledge_env(tmp_path):
    db_file = tmp_path / "knowledge_test.db"
    db = DatabaseManager(db_path=db_file)
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\Projects\Docs")
        fid = folder["folder_id"]

        f1 = repo.upsert_file(
            folder_id=fid,
            path=r"C:\Projects\Docs\plan_2025.md",
            relative_path="plan_2025.md",
            filename="plan_2025.md",
            extension=".md",
            size_bytes=500,
            modified_at="2025-01-01T00:00:00Z",
            file_id="f_plan_25",
        )
        repo.replace_file_chunks(
            "f_plan_25",
            [
                {
                    "chunk_id": "chk_p25_1",
                    "file_id": "f_plan_25",
                    "source_file": "plan_2025.md",
                    "source_path": r"C:\Projects\Docs\plan_2025.md",
                    "page": 1,
                    "section": "Roadmap",
                    "h1_parent": "2025 Goals",
                    "h2_parent": "Roadmap",
                    "line_start": 1,
                    "line_end": 5,
                    "char_start": 0,
                    "char_end": 100,
                    "content_hash": "h25",
                    "chunk_index": 0,
                    "parser_name": "md",
                    "parser_version": "1.0",
                    "chunker_version": "v1",
                    "content": "2025 Target: Reach 10,000 active users with single-node storage.",
                    "content_type": "text",
                    "token_count": 12,
                    "metadata": {},
                }
            ],
        )

        f2 = repo.upsert_file(
            folder_id=fid,
            path=r"C:\Projects\Docs\plan_2026.md",
            relative_path="plan_2026.md",
            filename="plan_2026.md",
            extension=".md",
            size_bytes=600,
            modified_at="2026-01-01T00:00:00Z",
            file_id="f_plan_26",
        )
        repo.replace_file_chunks(
            "f_plan_26",
            [
                {
                    "chunk_id": "chk_p26_1",
                    "file_id": "f_plan_26",
                    "source_file": "plan_2026.md",
                    "source_path": r"C:\Projects\Docs\plan_2026.md",
                    "page": 1,
                    "section": "Roadmap",
                    "h1_parent": "2026 Goals",
                    "h2_parent": "Roadmap",
                    "line_start": 1,
                    "line_end": 5,
                    "char_start": 0,
                    "char_end": 100,
                    "content_hash": "h26",
                    "chunk_index": 0,
                    "parser_name": "md",
                    "parser_version": "1.0",
                    "chunker_version": "v1",
                    "content": "2026 Target: Scale to 100,000 users and adopt local vector retrieval.",
                    "content_type": "text",
                    "token_count": 14,
                    "metadata": {},
                }
            ],
        )

    return db, "f_plan_25", "f_plan_26"


def test_compare_files_and_synthesis(knowledge_env):
    db, fid1, fid2 = knowledge_env

    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.model = "qwen3:4b"
    mock_provider.generate.return_value = OllamaResponse(
        model="qwen3:4b",
        response="Comparison: Plan 2025 focused on single-node [E1], while Plan 2026 targets vector scaling [E2].",
        done=True,
        done_reason="stop",
        prompt_eval_count=120,
        eval_count=30,
    )

    gen_service = GroundedGenerationService(provider=mock_provider)
    synthesis_svc = KnowledgeSynthesisService(
        db_manager_instance=db,
        generation_service=gen_service,
    )

    # 1. Compare Files
    comp_res = synthesis_svc.compare_files(
        file_ids=[fid1, fid2],
        aspects=["user targets", "architecture"],
    )
    assert len(comp_res["files"]) == 2
    assert "Comparison:" in comp_res["comparison_summary"]
    assert len(comp_res["citations"]) >= 2

    # 2. Synthesize Files
    mock_provider.generate.return_value = OllamaResponse(
        model="qwen3:4b",
        response="Synthesis: Growth from 10k to 100k users across both planning cycles [E1].",
        done=True,
        done_reason="stop",
        prompt_eval_count=100,
        eval_count=25,
    )
    synth_res = synthesis_svc.synthesize_files(file_ids=[fid1, fid2])
    assert "Synthesis:" in synth_res["synthesis"]
    assert len(synth_res["files"]) == 2
