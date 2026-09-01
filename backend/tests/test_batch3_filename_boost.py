"""Regression tests for Bug #18: Filename & Stem Boost Consolidation."""

import pytest
from app.retrieval.lexical import compute_filename_match_boost, extract_filename_stems


def test_extract_filename_stems():
    assert extract_filename_stems("archive.tar.gz") == ("archive.tar", "archive")
    assert extract_filename_stems("report.final.pdf") == ("report.final", "report")
    assert extract_filename_stems("sample.txt") == ("sample", "sample")
    assert extract_filename_stems("README") == ("README", "README")
    assert extract_filename_stems("") == ("", "")


def test_compute_filename_match_boost_bm25_domain():
    # Exact filename match
    boost = compute_filename_match_boost("sample.txt", ["sample", "txt"], "sample.txt", domain="bm25")
    assert boost == 5.0

    # Exact stem match
    boost = compute_filename_match_boost("sample", ["sample"], "sample.txt", domain="bm25")
    assert boost == 5.0

    # Token equals filename
    boost = compute_filename_match_boost("find sample.txt now", ["find", "sample.txt", "now"], "sample.txt", domain="bm25")
    assert boost == 3.0

    # Token matches stem
    boost = compute_filename_match_boost("find sample here", ["find", "sample", "here"], "sample.txt", domain="bm25")
    assert boost == 2.0

    # No match
    boost = compute_filename_match_boost("unrelated text", ["unrelated", "text"], "sample.txt", domain="bm25")
    assert boost == 0.0


def test_compute_filename_match_boost_rrf_domain():
    # Exact filename match
    boost = compute_filename_match_boost("sample.txt", ["sample", "txt"], "sample.txt", domain="rrf")
    assert boost == 0.0200

    # Exact stem match
    boost = compute_filename_match_boost("sample", ["sample"], "sample.txt", domain="rrf")
    assert boost == 0.0200

    # Token matches stem
    boost = compute_filename_match_boost("find sample here", ["find", "sample", "here"], "sample.txt", domain="rrf")
    assert boost == 0.0050

    # No match
    boost = compute_filename_match_boost("unrelated text", ["unrelated", "text"], "sample.txt", domain="rrf")
    assert boost == 0.0
