"""
Comprehensive test suite for Phase 5.1: Context Assembly + Token Budget Foundation.
"""

import pytest

from app.ai.context import (
    BoundedContextPackage,
    BudgetAccounting,
    ContextBudgetConfig,
    ContextBuilder,
    ContextItem,
    EvidenceStatus,
    OmissionReason,
    OmittedCandidate,
    TokenEstimator,
    default_context_builder,
)
from app.schemas import SearchResultItem


def _make_candidate(
    chunk_id: str,
    content: str,
    file_id: str = "file_123",
    source_file: str = "report.md",
    page: int = 1,
    section: str = "Introduction",
    score: float = 0.95,
) -> SearchResultItem:
    """Helper to create realistic SearchResultItem instances."""
    return SearchResultItem(
        rank=1,
        chunk_id=chunk_id,
        file_id=file_id,
        score=score,
        reranker_score=score,
        rrf_score=score,
        lexical_score=score,
        dense_score=score,
        retrieval_method="hybrid_rrf",
        source_file=source_file,
        source_path=f"C:\\docs\\{source_file}",
        page=page,
        section=section,
        h1_parent="Chapter 1",
        h2_parent=section,
        line_start=10,
        line_end=25,
        char_start=100,
        char_end=100 + len(content),
        snippet=content[:50],
        content=content,
        content_hash="hash_" + chunk_id,
        metadata={"author": "FileMind"},
    )


# ---------------------------------------------------------------------------
# Test 1: Empty Evidence
# ---------------------------------------------------------------------------
def test_empty_evidence():
    builder = ContextBuilder()
    pkg = builder.build_context([])

    assert pkg.status == EvidenceStatus.NO_EVIDENCE
    assert len(pkg.items) == 0
    assert pkg.budget.candidates_considered == 0
    assert pkg.budget.candidates_included == 0
    assert pkg.budget.candidates_omitted == 0
    assert pkg.budget.evidence_used == 0
    assert pkg.budget.evidence_remaining == pkg.budget.evidence_budget


# ---------------------------------------------------------------------------
# Test 2: One Small Chunk Fits
# ---------------------------------------------------------------------------
def test_one_small_chunk_fits():
    builder = ContextBuilder()
    cand = _make_candidate("chunk_1", "This is a brief summary of local intelligence.")
    pkg = builder.build_context([cand])

    assert pkg.status == EvidenceStatus.READY
    assert len(pkg.items) == 1
    assert pkg.items[0].chunk_id == "chunk_1"
    assert pkg.budget.candidates_included == 1
    assert pkg.budget.candidates_omitted == 0
    assert pkg.budget.evidence_used > 0
    assert pkg.budget.evidence_used <= pkg.budget.evidence_budget
    assert pkg.budget.evidence_remaining == pkg.budget.evidence_budget - pkg.budget.evidence_used


# ---------------------------------------------------------------------------
# Test 3: Multiple Chunks Fit
# ---------------------------------------------------------------------------
def test_multiple_chunks_fit():
    builder = ContextBuilder()
    cands = [
        _make_candidate(f"chunk_{i}", f"Paragraph number {i} with valuable technical context.")
        for i in range(5)
    ]
    pkg = builder.build_context(cands)

    assert pkg.status == EvidenceStatus.READY
    assert len(pkg.items) == 5
    assert pkg.budget.candidates_included == 5
    assert pkg.budget.candidates_omitted == 0
    # Check ordering is preserved
    for i in range(5):
        assert pkg.items[i].chunk_id == f"chunk_{i}"


# ---------------------------------------------------------------------------
# Test 4: Budget Boundary Respected Exactly
# ---------------------------------------------------------------------------
def test_budget_boundary_respected_exactly():
    estimator = TokenEstimator(chars_per_token_non_cjk=4.0)
    # Configure tight evidence budget of 100 tokens
    config = ContextBudgetConfig(
        max_context_tokens=1600,
        reserved_system_tokens=500,
        reserved_output_tokens=1000,  # leaves evidence_budget = 100
    )
    assert config.evidence_budget == 100

    builder = ContextBuilder(estimator=estimator, default_budget=config)
    # Each chunk is ~30 tokens (including framing)
    cands = [
        _make_candidate(f"chunk_{i}", "This chunk contains roughly thirty tokens of descriptive text.")
        for i in range(10)
    ]
    pkg = builder.build_context(cands, config)

    assert pkg.status == EvidenceStatus.READY
    assert pkg.budget.evidence_used <= 100
    assert len(pkg.items) > 0
    assert len(pkg.items) < 10
    assert pkg.budget.candidates_included + pkg.budget.candidates_omitted == 10
    assert pkg.budget.evidence_used + pkg.budget.evidence_remaining == 100


# ---------------------------------------------------------------------------
# Test 5: Chunk That Does Not Fit Is Omitted
# ---------------------------------------------------------------------------
def test_chunk_exceeding_remaining_budget_is_omitted():
    config = ContextBudgetConfig(
        max_context_tokens=1600,
        reserved_system_tokens=500,
        reserved_output_tokens=1000,  # evidence_budget = 100
    )
    builder = ContextBuilder(default_budget=config)

    # First candidate uses ~60 tokens
    c1 = _make_candidate("c1", "Small piece of text with moderate length " * 4)
    # Second candidate uses ~60 tokens (60 <= 100 total budget, but 60 + 60 > 100 remaining)
    c2 = _make_candidate("c2", "Another piece of text with moderate length " * 4)

    pkg = builder.build_context([c1, c2], config)

    assert len(pkg.items) == 1
    assert pkg.items[0].chunk_id == "c1"
    assert pkg.budget.candidates_omitted == 1
    omitted = pkg.budget.omitted_candidates[0]
    assert omitted.chunk_id == "c2"
    assert omitted.reason == OmissionReason.BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Test 6: Single Oversized Chunk Exceeding Total Evidence Budget
# ---------------------------------------------------------------------------
def test_oversized_single_chunk_omitted():
    config = ContextBudgetConfig(
        max_context_tokens=600,
        reserved_system_tokens=300,
        reserved_output_tokens=200,  # evidence_budget = 100
    )
    builder = ContextBuilder(default_budget=config)

    # Single massive chunk requiring ~300 tokens
    c1 = _make_candidate("massive_1", "Massive text block " * 100)
    pkg = builder.build_context([c1], config)

    assert pkg.status == EvidenceStatus.BUDGET_LIMITED
    assert len(pkg.items) == 0
    assert pkg.budget.candidates_included == 0
    assert pkg.budget.candidates_omitted == 1
    assert pkg.budget.omitted_candidates[0].reason == OmissionReason.OVERSIZED_SINGLE_CHUNK


# ---------------------------------------------------------------------------
# Test 7: Duplicate Chunk IDs Are Not Duplicated
# ---------------------------------------------------------------------------
def test_duplicate_chunk_deduplication():
    builder = ContextBuilder()
    c1 = _make_candidate("dup_chunk", "Evidence text.")
    c2 = _make_candidate("dup_chunk", "Evidence text duplicate.")
    c3 = _make_candidate("other_chunk", "Different evidence text.")

    pkg = builder.build_context([c1, c2, c3])

    assert len(pkg.items) == 2
    assert pkg.items[0].chunk_id == "dup_chunk"
    assert pkg.items[1].chunk_id == "other_chunk"
    assert pkg.budget.candidates_considered == 3
    assert pkg.budget.candidates_included == 2
    assert pkg.budget.candidates_omitted == 1
    assert pkg.budget.omitted_candidates[0].reason == OmissionReason.DUPLICATE_CHUNK


# ---------------------------------------------------------------------------
# Test 8: Provenance Survives Assembly
# ---------------------------------------------------------------------------
def test_provenance_integrity_preserved():
    builder = ContextBuilder()
    cand = _make_candidate(
        chunk_id="prov_chunk_99",
        content="Provenance verification content block.",
        file_id="file_abc_999",
        source_file="architecture.pdf",
        page=42,
        section="Storage Layer",
        score=0.88,
    )
    cand.metadata = {"confidential": False, "revision": 3, "parser_name": "pdf_structured"}

    pkg = builder.build_context([cand])

    assert len(pkg.items) == 1
    item = pkg.items[0]
    assert item.chunk_id == "prov_chunk_99"
    assert item.file_id == "file_abc_999"
    assert item.source_file == "architecture.pdf"
    assert item.source_path == "C:\\docs\\architecture.pdf"
    assert item.page == 42
    assert item.section == "Storage Layer"
    assert item.line_start == 10
    assert item.line_end == 25
    assert item.score == 0.88
    assert item.reranker_score == 0.88
    assert item.metadata == {"confidential": False, "revision": 3, "parser_name": "pdf_structured"}
    assert "[Source: architecture.pdf | Section: Storage Layer | Page: 42 | Lines: 10-25]" in item.format_grounded_block()


# ---------------------------------------------------------------------------
# Test 9: Retrieval Ordering Preserved Deterministically
# ---------------------------------------------------------------------------
def test_retrieval_ordering_preserved():
    builder = ContextBuilder()
    cands = [
        _make_candidate("c_first", "First rank candidate", score=0.99),
        _make_candidate("c_second", "Second rank candidate", score=0.85),
        _make_candidate("c_third", "Third rank candidate", score=0.70),
    ]
    pkg = builder.build_context(cands)

    assert [item.chunk_id for item in pkg.items] == ["c_first", "c_second", "c_third"]


# ---------------------------------------------------------------------------
# Test 10: Idempotence (Same Input Produces Identical Output)
# ---------------------------------------------------------------------------
def test_idempotence():
    builder = ContextBuilder()
    cands = [
        _make_candidate(f"c_{i}", f"Data point {i}")
        for i in range(4)
    ]
    pkg1 = builder.build_context(cands)
    pkg2 = builder.build_context(cands)

    assert pkg1.to_dict() == pkg2.to_dict()


# ---------------------------------------------------------------------------
# Test 11: Different Model Context Limits Produce Different Valid Budgets
# ---------------------------------------------------------------------------
def test_different_model_context_limits():
    cfg_small = ContextBudgetConfig(max_context_tokens=2048, reserved_system_tokens=300, reserved_output_tokens=500)
    cfg_large = ContextBudgetConfig(max_context_tokens=8192, reserved_system_tokens=500, reserved_output_tokens=1500)

    assert cfg_small.evidence_budget == 1248
    assert cfg_large.evidence_budget == 6192

    builder = ContextBuilder()
    cands = [_make_candidate(f"chunk_{i}", "Some text " * 20) for i in range(30)]

    pkg_small = builder.build_context(cands, cfg_small)
    pkg_large = builder.build_context(cands, cfg_large)

    assert pkg_small.budget.evidence_budget == 1248
    assert pkg_large.budget.evidence_budget == 6192
    assert len(pkg_small.items) <= len(pkg_large.items)


# ---------------------------------------------------------------------------
# Test 12: System + Output Reservations Reduce Evidence Budget
# ---------------------------------------------------------------------------
def test_reservations_math():
    cfg = ContextBudgetConfig(
        max_context_tokens=4000,
        reserved_system_tokens=1000,
        reserved_output_tokens=1500,
    )
    assert cfg.evidence_budget == 1500

    builder = ContextBuilder()
    pkg = builder.build_context([], cfg)
    assert pkg.budget.total_budget == 4000
    assert pkg.budget.system_reserved == 1000
    assert pkg.budget.output_reserved == 1500
    assert pkg.budget.evidence_budget == 1500


# ---------------------------------------------------------------------------
# Test 13: Evidence Used Never Exceeds Evidence Budget
# ---------------------------------------------------------------------------
def test_evidence_used_invariant():
    cfg = ContextBudgetConfig(max_context_tokens=2000, reserved_system_tokens=500, reserved_output_tokens=1000)
    builder = ContextBuilder(default_budget=cfg)

    cands = [_make_candidate(f"c_{i}", "Paragraph " * 50) for i in range(20)]
    pkg = builder.build_context(cands, cfg)

    assert pkg.budget.evidence_used <= cfg.evidence_budget
    assert pkg.budget.evidence_remaining >= 0


# ---------------------------------------------------------------------------
# Test 14: Omission Reporting Details
# ---------------------------------------------------------------------------
def test_omission_details_reporting():
    cfg = ContextBudgetConfig(max_context_tokens=1550, reserved_system_tokens=500, reserved_output_tokens=1000)  # 50 tokens evidence
    builder = ContextBuilder(default_budget=cfg)

    # First candidate uses ~35 tokens
    c1 = _make_candidate("c1", "Fits in 50 tokens budget easily.")
    # Second candidate uses ~35 tokens (35 <= 50, but 35 + 35 = 70 > 50)
    c2 = _make_candidate("c2", "This second chunk exceeds the remaining budget.")

    pkg = builder.build_context([c1, c2], cfg)
    assert pkg.budget.candidates_omitted >= 1
    omitted = pkg.budget.omitted_candidates[0]
    assert omitted.chunk_id == "c2"
    assert omitted.reason == OmissionReason.BUDGET_EXCEEDED
    assert "exceed remaining budget" in omitted.details


# ---------------------------------------------------------------------------
# Test 15: Empty/Invalid Chunk Text Handled Safely
# ---------------------------------------------------------------------------
def test_empty_chunk_text_handled_safely():
    builder = ContextBuilder()
    c1 = _make_candidate("empty_1", "")
    c2 = _make_candidate("whitespace_1", "   \n\t  ")
    c3 = _make_candidate("valid_1", "Real content.")

    pkg = builder.build_context([c1, c2, c3])

    assert len(pkg.items) == 1
    assert pkg.items[0].chunk_id == "valid_1"
    assert pkg.budget.candidates_considered == 3
    assert pkg.budget.candidates_omitted == 2
    assert all(o.reason == OmissionReason.INVALID_EMPTY_CONTENT for o in pkg.budget.omitted_candidates)


# ---------------------------------------------------------------------------
# Test 16: Massive Scale Input Safety
# ---------------------------------------------------------------------------
def test_massive_scale_candidate_stream_safety():
    cfg = ContextBudgetConfig(max_context_tokens=4096, reserved_system_tokens=500, reserved_output_tokens=1000, max_chunks=20)
    builder = ContextBuilder(default_budget=cfg)

    # 300 candidates with varied sizes
    cands = [_make_candidate(f"c_{i}", f"Candidate content block number {i} " * 10) for i in range(300)]
    pkg = builder.build_context(cands, cfg)

    assert pkg.status == EvidenceStatus.READY
    assert len(pkg.items) <= 20
    assert pkg.budget.evidence_used <= cfg.evidence_budget
    assert pkg.budget.candidates_considered == 300
    assert pkg.budget.candidates_included + pkg.budget.candidates_omitted == 300


# ---------------------------------------------------------------------------
# Test 17: Token Estimator Heuristics (Deterministic & CJK / Latin)
# ---------------------------------------------------------------------------
def test_token_estimator_heuristics():
    est = TokenEstimator(chars_per_token_non_cjk=3.5)

    assert est.estimate("") == 0
    assert est.estimate("   ") == 0
    assert est.estimate(None) == 0
    assert est.estimate("a") >= 1

    # Latin text: 35 characters -> ~10 tokens
    latin_35 = "a" * 35
    assert est.estimate(latin_35) == 10

    # CJK text: 10 characters -> 10 tokens
    cjk_10 = "人工智能文件检索系统测试"
    assert est.estimate(cjk_10) == 12  # CJK chars count as 1 token each

    # Framing overhead
    framing = est.estimate_framing_overhead("test.txt", section="Sec 1", page=1)
    assert framing > 0


# ---------------------------------------------------------------------------
# Test 18: Max Chunks Cap
# ---------------------------------------------------------------------------
def test_max_chunks_cap():
    cfg = ContextBudgetConfig(
        max_context_tokens=10000,
        reserved_system_tokens=500,
        reserved_output_tokens=1000,
        max_chunks=3,
    )
    builder = ContextBuilder(default_budget=cfg)

    cands = [_make_candidate(f"c_{i}", "Short text") for i in range(10)]
    pkg = builder.build_context(cands, cfg)

    assert len(pkg.items) == 3
    assert pkg.budget.candidates_included == 3
    assert pkg.budget.candidates_omitted == 7
    assert pkg.budget.omitted_candidates[0].reason == OmissionReason.MAX_CHUNKS_REACHED


# ---------------------------------------------------------------------------
# Test 19: Edge Case: 0 Token Budget
# ---------------------------------------------------------------------------
def test_zero_token_budget():
    cfg = ContextBudgetConfig(
        max_context_tokens=1000,
        reserved_system_tokens=500,
        reserved_output_tokens=500,  # leaves evidence_budget = 0
    )
    assert cfg.evidence_budget == 0

    builder = ContextBuilder(default_budget=cfg)
    cand = _make_candidate("c1", "Any text at all.")
    pkg = builder.build_context([cand], cfg)

    assert pkg.status == EvidenceStatus.BUDGET_LIMITED
    assert len(pkg.items) == 0
    assert pkg.budget.evidence_used == 0
    assert pkg.budget.candidates_omitted == 1
