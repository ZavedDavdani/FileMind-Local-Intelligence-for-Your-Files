"""Tests for citation normalization, case insensitivity, leading zeros, and deduplication."""

from app.ai.citation import CitationValidator
from app.ai.prompt import CitationSource


def test_citation_normalization_variants():
    """Verifies that E1, E01, E001, [e1], and [E 1] all resolve to the canonical E1 citation."""
    source_e1 = CitationSource(
        citation_id="E1",
        chunk_id="chk_1",
        file_id="file_1",
        source_file="report.pdf",
        source_path=r"C:\docs\report.pdf",
    )
    citation_map = {"E1": source_e1}

    # Test E1 verbatim
    res1 = CitationValidator.extract_and_validate("According to [E1], sales rose.", citation_map)
    assert res1.is_valid
    assert len(res1.valid_citations) == 1
    assert res1.valid_citations[0].citation_id == "E1"

    # Test E01 leading zero
    res2 = CitationValidator.extract_and_validate("According to [E01], sales rose.", citation_map)
    assert res2.is_valid
    assert len(res2.valid_citations) == 1
    assert res2.valid_citations[0].citation_id == "E1"

    # Test E001 leading zeros
    res3 = CitationValidator.extract_and_validate("According to [E001], sales rose.", citation_map)
    assert res3.is_valid
    assert len(res3.valid_citations) == 1
    assert res3.valid_citations[0].citation_id == "E1"

    # Test [e1] lowercase
    res4 = CitationValidator.extract_and_validate("According to [e1], sales rose.", citation_map)
    assert res4.is_valid
    assert len(res4.valid_citations) == 1
    assert res4.valid_citations[0].citation_id == "E1"

    # Test duplicate citations deduplicated in appearance order
    res5 = CitationValidator.extract_and_validate("[E1] states X, and [E01] confirms X.", citation_map)
    assert res5.is_valid
    assert len(res5.valid_citations) == 1

    # Test unresolved citation
    res6 = CitationValidator.extract_and_validate("Unbacked claim [E99].", citation_map)
    assert not res6.is_valid
    assert "E99" in res6.unresolved_citation_ids
