"""Unit tests for Phase 3 Query Normalization."""

import pytest
from app.retrieval.normalizer import normalize_query


def test_empty_and_whitespace_queries():
    assert normalize_query("").is_empty
    assert normalize_query("   ").is_empty
    assert normalize_query(None).is_empty
    assert normalize_query("\t\n  \r").is_empty


def test_case_and_whitespace_normalization():
    res = normalize_query("  SQLite   WAL   ARCHITECTURE  ")
    assert not res.is_empty
    assert res.normalized_query == "SQLite WAL ARCHITECTURE"
    assert res.tokens == ["SQLite", "WAL", "ARCHITECTURE"]
    assert '"SQLite"*' in res.fts5_query
    assert '"WAL"*' in res.fts5_query


def test_preserve_technical_identifiers():
    res = normalize_query("SHA-256 v1.0.0 file_events sqlite-vec H1/H2")
    assert not res.is_empty
    assert "SHA-256" in res.tokens
    assert "v1.0.0" in res.tokens
    assert "file_events" in res.tokens
    assert "sqlite-vec" in res.tokens
    assert "H1/H2" in res.tokens


def test_quoted_phrase_extraction():
    res = normalize_query('Search for "Write-Ahead Logging" in persistence')
    assert not res.is_empty
    assert "Write-Ahead Logging" in res.phrases
    assert '"Write-Ahead Logging"' in res.fts5_query
    assert '"persistence"*' in res.fts5_query


def test_fts5_special_syntax_safety():
    # Test queries with potential FTS5 operator collisions
    res = normalize_query("AND OR NOT NEAR * : ^")
    assert not res.is_empty
    assert '"AND"' in res.fts5_query
    assert '"OR"' in res.fts5_query
    assert '"NOT"' in res.fts5_query
    assert '"NEAR"' in res.fts5_query


def test_code_snippet_query():
    res = normalize_query("def execute_task(self, task_id: str)")
    assert not res.is_empty
    assert "execute_task" in res.tokens
    assert "task_id" in res.tokens
