"""
Regression test suite for Remediation Chunk 1 (Findings 1-6):
- Finding 1: SVG XXE / unsafe XML parsing
- Finding 2: XML XXE / unsafe XML parsing
- Finding 3: Bounded legacy binary extraction
- Finding 4: RTF control-word stripping and unescaping
- Finding 5: Persistent Chat multi-turn conversation history
- Finding 6: Compare/Synthesize truthful scoring & evidence selection
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock

from app.intelligence.parsers.image_parser import ImageParser
from app.intelligence.parsers.tabular_parser import TabularParser
from app.intelligence.parsers.legacy_doc_ppt_parser import (
    LegacyOfficeParser,
    extract_binary_text_streams,
    MAX_LEGACY_READ_BYTES,
)
from app.intelligence.parsers.rtf_html_parser import RtfAndHtmlParser, extract_rtf_text
from app.intelligence.parsers.base import CorruptedDocumentError

from app.ai.context import ContextBuilder, ContextItem, BoundedContextPackage, EvidenceStatus
from app.ai.prompt import PromptBuilder
from app.ai.generation import (
    GroundedGenerationService,
    GroundedGenerationRequest,
    GenerationStatus,
    ModelIdentity,
)
from app.ai.chat_service import ChatService
from app.ai.knowledge_synthesis import KnowledgeSynthesisService
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.schemas import ConversationCreate, SendChatMessageRequest


# =========================================================================
# Finding 1 & 2: SVG XXE & XML XXE Tests
# =========================================================================

def test_svg_xxe_payload_rejection():
    """Finding 1: Verify SVG with XXE / DTD expansion is safely rejected without reading files."""
    parser = ImageParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        canary_path = os.path.join(tmp_dir, "canary.txt")
        with open(canary_path, "w", encoding="utf-8") as f:
            f.write("SECRET_CANARY_TOKEN_12345")

        xxe_svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg [
  <!ENTITY xxe SYSTEM "file:///{canary_path.replace(os.sep, '/')}">
]>
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <text x="10" y="20">&xxe;</text>
</svg>"""
        svg_file = os.path.join(tmp_dir, "malicious.svg")
        with open(svg_file, "w", encoding="utf-8") as f:
            f.write(xxe_svg)

        with pytest.raises(CorruptedDocumentError):
            parser.parse(svg_file, file_id="test_svg_1", mime_type="image/svg+xml")


def test_valid_svg_parsing_intact():
    """Finding 1: Verify legitimate SVG text extraction functions properly."""
    parser = ImageParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        valid_svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="200" height="100" xmlns="http://www.w3.org/2000/svg">
  <title>Architecture Overview</title>
  <text x="10" y="20">FileMind Local Engine</text>
</svg>"""
        svg_file = os.path.join(tmp_dir, "valid.svg")
        with open(svg_file, "w", encoding="utf-8") as f:
            f.write(valid_svg)

        doc = parser.parse(svg_file, file_id="test_svg_2", mime_type="image/svg+xml")
        assert doc is not None
        assert len(doc.elements) >= 1
        combined_text = "\n".join(e.text for e in doc.elements)
        assert "Architecture Overview" in combined_text
        assert "FileMind Local Engine" in combined_text


def test_xml_xxe_payload_rejection():
    """Finding 2: Verify XML parser blocks XXE and external entity resolution."""
    parser = TabularParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        canary_path = os.path.join(tmp_dir, "canary.txt")
        with open(canary_path, "w", encoding="utf-8") as f:
            f.write("CONFIDENTIAL_DATABASE_PASSWORD")

        malicious_xml = f"""<?xml version="1.0"?>
<!DOCTYPE data [
  <!ENTITY payload SYSTEM "file:///{canary_path.replace(os.sep, '/')}">
]>
<catalog>
  <book>
    <title>&payload;</title>
  </book>
</catalog>"""
        xml_file = os.path.join(tmp_dir, "attack.xml")
        with open(xml_file, "w", encoding="utf-8") as f:
            f.write(malicious_xml)

        with pytest.raises(CorruptedDocumentError):
            parser.parse(xml_file, file_id="test_xml_1", mime_type="application/xml")


# =========================================================================
# Finding 3: Bounded Legacy Binary Extraction Tests
# =========================================================================

def test_legacy_binary_bounded_extraction():
    """Finding 3: Verify legacy binary extractor enforces bounds and handles malformed data."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        doc_file = os.path.join(tmp_dir, "sample.doc")
        with open(doc_file, "wb") as f:
            f.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
            f.write(b"\x00" * 50)
            f.write("Confidential Strategy Document".encode("utf-16le"))
            f.write(b"\x00" * 20)
            f.write(b"Legacy ASCII Paragraph Data Here For Testing")
            f.write(b"\x00" * 30)

        runs = extract_binary_text_streams(doc_file, max_read_bytes=1024, max_runs=10)
        assert len(runs) >= 2
        assert any("Confidential Strategy Document" in r for r in runs)
        assert any("Legacy ASCII Paragraph Data Here" in r for r in runs)

        runs_bounded = extract_binary_text_streams(doc_file, max_runs=1)
        assert len(runs_bounded) == 1

        empty_doc = os.path.join(tmp_dir, "empty.doc")
        with open(empty_doc, "wb") as f:
            pass
        assert extract_binary_text_streams(empty_doc) == []


# =========================================================================
# Finding 4: RTF Control-Word Stripping Tests
# =========================================================================

def test_rtf_control_word_stripping_and_unescaping():
    """Finding 4: Verify RTF control words, metadata groups, and escaped characters are properly parsed."""
    rtf_content = r"""{\rtf1\ansi\ansicpg1252\deff0\nouicompat\deflang1033
{\fonttbl{\f0\fnil\fcharset0 Calibri;}{\f1\fnil\fcharset2 Symbol;}}
{\colortbl ;\red0\green77\blue187;\red255\green0\blue0;}
{\*\generator FileMind RTF Test;}
\viewkind4\uc1 
\pard\cf1\b\f0\fs28 Executive Summary\b0\par
\pard\cf0\fs22 This is a critical document with \{escaped braces\} and a backslash: \\.\par
Special characters: \u8212? emdash, and \'e9 clair pastry.\par
}"""

    paras = extract_rtf_text(rtf_content)
    assert len(paras) == 3
    assert paras[0] == "Executive Summary"
    assert paras[1] == "This is a critical document with {escaped braces} and a backslash: \\."
    assert "emdash" in paras[2]

    full_text = " ".join(paras)
    for forbidden in [r"\rtf1", r"\fonttbl", r"\colortbl", r"\pard", r"\cf1", r"\fs28", r"\b0", r"\par"]:
        assert forbidden not in full_text


# =========================================================================
# Finding 5: Persistent Chat Multi-Turn History Tests
# =========================================================================

def test_chat_multi_turn_history_in_prompt():
    """Finding 5: Verify build_prompt and ChatService include prior conversational turns."""
    builder = PromptBuilder()
    ctx_builder = ContextBuilder()

    candidates = [{
        "chunk_id": "chk_1",
        "file_id": "f_1",
        "source_file": "q3_report.pdf",
        "source_path": "/docs/q3_report.pdf",
        "content": "Q3 Revenue reached $14.2M, representing 18% YoY growth.",
    }]
    pkg = ctx_builder.build_context(candidates)

    history = [
        {"role": "user", "content": "What is our company name?"},
        {"role": "assistant", "content": "The company name is FileMind Inc. [E1]"},
    ]

    prompt_obj = builder.build_prompt(
        query="What was our revenue in Q3?",
        context_package=pkg,
        history=history,
    )

    prompt_text = prompt_obj.full_prompt
    assert "--- CONVERSATION HISTORY ---" in prompt_text
    assert "User: What is our company name?" in prompt_text
    assert "Assistant: The company name is FileMind Inc. [E1]" in prompt_text
    assert "--- EVIDENCE ---" in prompt_text
    assert "Q3 Revenue reached $14.2M" in prompt_text
    assert "--- USER QUESTION ---" in prompt_text
    assert "What was our revenue in Q3?" in prompt_text


def test_chat_service_multi_turn_e2e():
    """Finding 5: End-to-end multi-turn chat records and supplies previous messages."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "chat_test.db")
        db_mgr = DatabaseManager(db_path=db_path)
        with db_mgr.session() as conn:
            apply_migrations(conn)

        fake_gen_service = MagicMock(spec=GroundedGenerationService)
        fake_gen_service.generate_answer.return_value = MagicMock(
            answer="Q3 Revenue was $14.2M [E1]",
            query="What was our Q3 revenue?",
            generation_status=GenerationStatus.READY,
            evidence_status=EvidenceStatus.READY,
            citations=[],
            unresolved_citations=[],
            model_identity=ModelIdentity(provider="fake", model_name="fake", is_local=True),
        )

        chat_svc = ChatService(
            db_manager=db_mgr,
            generation_service=fake_gen_service,
        )

        conv = chat_svc.create_conversation(ConversationCreate(title="Test Chat", scope_type="ALL"))
        cid = conv.conversation_id

        # Turn 1
        chat_svc.send_message(cid, SendChatMessageRequest(content="Hello assistant"))
        assert fake_gen_service.generate_answer.call_count == 1
        assert fake_gen_service.generate_answer.call_args[1].get("history") == []

        # Turn 2
        chat_svc.send_message(cid, SendChatMessageRequest(content="What was our Q3 revenue?"))
        assert fake_gen_service.generate_answer.call_count == 2
        history_arg = fake_gen_service.generate_answer.call_args[1].get("history")
        assert history_arg is not None
        assert len(history_arg) >= 1
        assert history_arg[0]["role"] == "user"
        assert history_arg[0]["content"] == "Hello assistant"


# =========================================================================
# Finding 6: Compare & Synthesize Truthful Scoring Tests
# =========================================================================

def test_compare_and_synthesis_truthful_scoring():
    """Finding 6: Verify comparison and synthesis do not assign artificial score=1.0."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "synth_test.db")
        db_mgr = DatabaseManager(db_path=db_path)
        with db_mgr.session() as conn:
            apply_migrations(conn)

        with db_mgr.session() as conn:
            repo = Repository(conn)
            fldr = repo.create_folder(tmp_dir)
            fid_root = fldr["folder_id"]

            f1 = repo.upsert_file(fid_root, f"{tmp_dir}/f1.txt", "f1.txt", "f1.txt", ".txt", 100, "2026-08-30T12:00:00Z", index_status="INDEXED")
            f2 = repo.upsert_file(fid_root, f"{tmp_dir}/f2.txt", "f2.txt", "f2.txt", ".txt", 100, "2026-08-30T12:00:00Z", index_status="INDEXED")

            repo.replace_file_chunks(f1["file_id"], [
                {"chunk_id": "c1", "file_id": f1["file_id"], "chunk_index": 0, "content": "File 1 Architecture", "source_file": "f1.txt", "source_path": f"{tmp_dir}/f1.txt", "token_count": 5}
            ])
            repo.replace_file_chunks(f2["file_id"], [
                {"chunk_id": "c2", "file_id": f2["file_id"], "chunk_index": 0, "content": "File 2 Architecture", "source_file": "f2.txt", "source_path": f"{tmp_dir}/f2.txt", "token_count": 5}
            ])

        fake_gen_service = MagicMock(spec=GroundedGenerationService)
        fake_gen_service.generate_answer.return_value = MagicMock(
            answer="Comparing File 1 and File 2 [E1][E2]",
            query="Compare...",
            generation_status=GenerationStatus.READY,
            evidence_status=EvidenceStatus.READY,
            citations=[
                MagicMock(citation_id="E1", chunk_id="c1", file_id=f1["file_id"], source_file="f1.txt", source_path=f"{tmp_dir}/f1.txt", page=None, section=None, score=None),
                MagicMock(citation_id="E2", chunk_id="c2", file_id=f2["file_id"], source_file="f2.txt", source_path=f"{tmp_dir}/f2.txt", page=None, section=None, score=None),
            ],
            model_identity=ModelIdentity(provider="fake", model_name="fake", is_local=True),
        )

        synth_svc = KnowledgeSynthesisService(
            db_manager=db_mgr,
            generation_service=fake_gen_service,
        )

        comp_res = synth_svc.compare_files([f1["file_id"], f2["file_id"]])
        assert comp_res is not None
        assert len(comp_res["citations"]) == 2
        for cit in comp_res["citations"]:
            assert cit["score"] is None, f"Expected score=None for un-scored candidate, got {cit['score']}"

        synth_res = synth_svc.synthesize_files([f1["file_id"], f2["file_id"]])
        assert synth_res is not None
        for cit in synth_res["citations"]:
            assert cit["score"] is None, f"Expected score=None for un-scored candidate, got {cit['score']}"
