"""Tests for multiformat and multimodal retrieval, hierarchical chunking, and citations."""

import json
from pathlib import Path
import pytest
import sqlite3

from app.ai.ask_service import AskService
from app.ai.citation import CitationValidator
from app.ai.context import ContextBuilder, ContextItem
from app.ai.generation import GenerationConfig, GroundedGenerationResponse, ModelIdentity
from app.ai.prompt import CitationSource, PromptBuilder
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repositories.chunks import ChunkRepository
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.chunker.provenance import ChunkProvenance
from app.intelligence.models import Document, DocumentElement, ElementType
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.vector_store import SqliteVecStore


class TestMultimodalChunker:
    def test_chunker_extracts_and_propagates_multimodal_provenance(self):
        chunker = HierarchicalChunker(target_chunk_chars=1200, max_chunk_chars=2400)
        elements = [
            DocumentElement(
                element_id="el-1",
                element_type=ElementType.TABLE,
                text="Product,Q1 Sales,Q2 Sales\nWidget A,500,650\nWidget B,400,480",
                sheet_name="Sales Summary",
                media_type="tabular",
                extraction_method="native",
                char_start=0,
                char_end=75,
            ),
            DocumentElement(
                element_id="el-2",
                element_type=ElementType.TRANSCRIPT_SEGMENT,
                text="The quarterly revenue exceeded initial conservative projections across all segments.",
                time_start=15.0,
                time_end=45.0,
                media_type="audio",
                extraction_method="transcription",
                char_start=76,
                char_end=170,
            ),
            DocumentElement(
                element_id="el-3",
                element_type=ElementType.IMAGE_CAPTION,
                text="Architecture diagram showing local-first vector indexing and SQLite WAL storage.",
                frame_index=2,
                media_type="image",
                extraction_method="vision_description",
                char_start=171,
                char_end=260,
            ),
        ]
        doc = Document(
            file_id="file-multi-1",
            filename="report.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            source_path="/data/report.xlsx",
            parser_name="tabular-parser",
            parser_version="1.0.0",
            elements=elements,
        )

        chunks = chunker.chunk_document(doc)
        assert len(chunks) >= 3

        # Check table chunk provenance
        c_table = [c for c in chunks if c.sheet_name == "Sales Summary"][0]
        assert c_table.media_type == "tabular"
        assert c_table.sheet_name == "Sales Summary"
        assert c_table.content_type == "table"

        # Check audio transcript chunk provenance
        c_audio = [c for c in chunks if c.time_start == 15.0][0]
        assert c_audio.media_type == "audio"
        assert c_audio.time_start == 15.0
        assert c_audio.time_end == 45.0
        assert c_audio.content_type == "transcript"

        # Check visual caption chunk provenance
        c_img = [c for c in chunks if c.frame_index == 2][0]
        assert c_img.media_type == "image"
        assert c_img.frame_index == 2
        assert c_img.content_type == "visual"


class TestChunkRepositoryAndRetrievalHydration:
    def test_chunk_repository_saves_and_hydrates_multimodal_metadata(self, tmp_path):
        db_path = str(tmp_path / "test_mm.db")
        db_mgr = DatabaseManager(db_path)
        with db_mgr.session() as conn:
            apply_migrations(conn)
            repo = ChunkRepository(conn)
            test_chunk = ChunkProvenance(
                chunk_id="chunk-mm-1",
                file_id="file-mm-1",
                source_file="recording.mp3",
                source_path="/data/recording.mp3",
                time_start=75.0,
                time_end=105.0,
                media_type="audio",
                extraction_method="transcription",
                content="Key discussion on local privacy guarantees and fast hybrid search.",
                content_type="transcript",
                token_count=18,
                content_hash="hash-123",
            )

            # Create prerequisite file record
            conn.execute(
                """
                INSERT OR IGNORE INTO folders (folder_id, path) VALUES ('f1', '/data');
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO files (file_id, folder_id, path, relative_path, filename, extension, size_bytes, modified_at, index_status)
                VALUES ('file-mm-1', 'f1', '/data/recording.mp3', 'recording.mp3', 'recording.mp3', '.mp3', 1024, datetime('now'), 'INDEXED');
                """
            )

            repo.replace_file_chunks("file-mm-1", [test_chunk])

            fetched = repo.get_chunk_by_id("chunk-mm-1")
            assert fetched is not None
            assert fetched["time_start"] == 75.0
            assert fetched["time_end"] == 105.0
            assert fetched["media_type"] == "audio"
            assert fetched["extraction_method"] == "transcription"
            assert fetched["metadata"]["time_start"] == 75.0

    def test_prompt_builder_formats_rich_provenance_headers(self):
        builder = PromptBuilder()
        item = ContextItem(
            chunk_id="c1",
            file_id="f1",
            source_file="podcast.mp3",
            source_path="/data/podcast.mp3",
            content="Discussion of AI safety and local indexing.",
            estimated_tokens=25,
            time_start=15.0,
            time_end=45.0,
            media_type="audio",
            extraction_method="transcription",
        )
        item_block = item.format_grounded_block()
        assert "Source: podcast.mp3" in item_block
        assert "Timestamp: [00:15 - 00:45]" in item_block
        assert "Media: AUDIO" in item_block
        assert "Method: transcription" in item_block

        from app.ai.context import BoundedContextPackage, BudgetAccounting, EvidenceStatus
        pkg = BoundedContextPackage(
            status=EvidenceStatus.READY,
            items=[item],
            budget=BudgetAccounting(
                total_budget=4096, system_reserved=500, output_reserved=1000,
                evidence_budget=2596, evidence_used=25, evidence_remaining=2571,
                candidates_considered=1, candidates_included=1, candidates_omitted=0
            )
        )
        prompt = builder.build_prompt("What was discussed?", pkg)
        assert "[E1]" in prompt.full_prompt
        assert "podcast.mp3" in prompt.full_prompt
        assert "00:15 - 00:45" in prompt.full_prompt
        assert "E1" in prompt.citation_map
        assert prompt.citation_map["E1"].time_start == 15.0


class TestCitationValidationMultimodal:
    def test_citation_validation_with_multimodal_sources(self):
        source_doc = CitationSource(
            citation_id="E1", chunk_id="c1", file_id="f1",
            source_file="specs.pdf", source_path="/data/specs.pdf", page=3
        )
        source_audio = CitationSource(
            citation_id="E2", chunk_id="c2", file_id="f2",
            source_file="interview.mp3", source_path="/data/interview.mp3",
            time_start=60.0, time_end=90.0, media_type="audio"
        )
        source_sheet = CitationSource(
            citation_id="E3", chunk_id="c3", file_id="f3",
            source_file="budget.xlsx", source_path="/data/budget.xlsx",
            sheet_name="2026 Projections", media_type="tabular"
        )

        citation_map = {"E1": source_doc, "E2": source_audio, "E3": source_sheet}

        answer = (
            "The architecture specifications specify local storage [E1]. "
            "In the recorded interview, the team confirmed offline capability [E2]. "
            "The budget allocates 40% to performance optimization [E3]."
        )

        result = CitationValidator.extract_and_validate(answer, citation_map, require_citations=True)
        assert result.is_valid is True
        assert len(result.valid_citations) == 3
        assert result.valid_citations[0].citation_id == "E1"
        assert result.valid_citations[1].citation_id == "E2"
        assert result.valid_citations[1].time_start == 60.0
        assert result.valid_citations[2].citation_id == "E3"
        assert result.valid_citations[2].sheet_name == "2026 Projections"
