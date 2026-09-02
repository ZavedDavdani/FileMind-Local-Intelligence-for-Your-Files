"""Evaluation test suite for Bug #20: Multilingual & CJK Prefix Retrieval.

Evaluates:
- Chinese (Simplified/Traditional) tokens
- Japanese (Hiragana/Katakana/Kanji) tokens
- Korean (Hangul) tokens
- Cyrillic / Greek non-Latin scripts
- Mixed Latin + CJK queries
- FTS5 unicode61 tokenizer boundary vs prefix behavior
"""

import sqlite3
import pytest
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.hierarchical import estimate_token_count
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.normalizer import normalize_query



@pytest.fixture
def cjk_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    repo = Repository(conn)

    # Insert sample files and multilingual chunks
    files_data = [
        ("f_zh", "folder_1", "/docs/chinese.txt", "chinese.txt", "chinese", ".txt"),
        ("f_ja", "folder_1", "/docs/japanese.txt", "japanese.txt", "japanese", ".txt"),
        ("f_ko", "folder_1", "/docs/korean.txt", "korean.txt", "korean", ".txt"),
        ("f_ru", "folder_1", "/docs/russian.txt", "russian.txt", "russian", ".txt"),
        ("f_el", "folder_1", "/docs/greek.txt", "greek.txt", "greek", ".txt"),
        ("f_mix", "folder_1", "/docs/mixed.txt", "mixed.txt", "mixed", ".txt"),
    ]

    for fid, foid, path, rpath, fname, ext in files_data:
        repo.upsert_file(
            folder_id=foid,
            path=path,
            relative_path=rpath,
            filename=fname,
            extension=ext,
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            index_status="INDEXED",
            file_id=fid,
        )

    chunks_data = [
        ("c_zh1", "f_zh", "chinese.txt", "/docs/chinese.txt", "人工智能 是 计算机 科学 的 重要 分支。 深度 学习 在 自然 语言 处理 中 广泛 应用。"),
        ("c_ja1", "f_ja", "japanese.txt", "/docs/japanese.txt", "ファイル 検索 システム と 機械 学習 モデル の 統合。 日本語 テキスト の 解析。"),
        ("c_ko1", "f_ko", "korean.txt", "/docs/korean.txt", "인공지능 기반 파일 검색 시스템 아키텍처 및 벡터 검색 기능."),
        ("c_ru1", "f_ru", "russian.txt", "/docs/russian.txt", "Архитектура локального поиска файлов и векторизация документов."),
        ("c_el1", "f_el", "greek.txt", "/docs/greek.txt", "Αναζήτηση αρχείων και ανάλυση εγγράφων με μηχανική μάθηση."),
        ("c_mix1", "f_mix", "mixed.txt", "/docs/mixed.txt", "FileMind 智能搜索 SQLite-Vec FastEmbed ハイブリッド 검색."),
    ]

    for cid, fid, sfile, spath, content in chunks_data:
        chunk = ChunkProvenance(
            chunk_id=cid,
            file_id=fid,
            source_file=sfile,
            source_path=spath,
            page=None,
            section=None,
            h1_parent=None,
            h2_parent=None,
            line_start=1,
            line_end=1,
            char_start=0,
            char_end=len(content),
            content_hash=f"hash_{cid}",
            chunk_index=0,
            parser_name="text_parser",
            parser_version="1.0",
            chunker_version="1.0",
            content=content,
            content_type="text",
            token_count=estimate_token_count(content),
        )

        repo.replace_file_chunks(fid, [chunk])

    return conn


def test_chinese_query_evaluation(cjk_db):
    retriever = LexicalRetriever(cjk_db)

    # 1. Chinese multi-character term
    norm_q = normalize_query("人工智能")
    assert not norm_q.is_empty
    results = retriever.search(norm_q, top_k=5)
    assert len(results) >= 1
    assert any(r["chunk_id"] == "c_zh1" for r in results)

    # 2. Chinese sub-term
    norm_q2 = normalize_query("自然 语言 处理")
    results2 = retriever.search(norm_q2, top_k=5)
    assert len(results2) >= 1
    assert any(r["chunk_id"] == "c_zh1" for r in results2)


def test_japanese_query_evaluation(cjk_db):
    retriever = LexicalRetriever(cjk_db)

    # 1. Katakana prefix query
    norm_q = normalize_query("ファイル")
    results = retriever.search(norm_q, top_k=5)
    assert len(results) >= 1
    assert any(r["chunk_id"] == "c_ja1" for r in results)

    # 2. Kanji query
    norm_q2 = normalize_query("機械 学習")
    results2 = retriever.search(norm_q2, top_k=5)
    assert len(results2) >= 1
    assert any(r["chunk_id"] == "c_ja1" for r in results2)


def test_korean_query_evaluation(cjk_db):
    retriever = LexicalRetriever(cjk_db)

    # Hangul query
    norm_q = normalize_query("인공지능")
    results = retriever.search(norm_q, top_k=5)
    assert len(results) >= 1
    assert any(r["chunk_id"] == "c_ko1" for r in results)


def test_cyrillic_and_greek_query_evaluation(cjk_db):
    retriever = LexicalRetriever(cjk_db)

    # Cyrillic query
    norm_q_ru = normalize_query("векторизация")
    results_ru = retriever.search(norm_q_ru, top_k=5)
    assert len(results_ru) >= 1
    assert any(r["chunk_id"] == "c_ru1" for r in results_ru)

    # Greek query
    norm_q_el = normalize_query("Αναζήτηση")
    results_el = retriever.search(norm_q_el, top_k=5)
    assert len(results_el) >= 1
    assert any(r["chunk_id"] == "c_el1" for r in results_el)


def test_mixed_script_query_evaluation(cjk_db):
    retriever = LexicalRetriever(cjk_db)

    # Mixed Latin + Chinese
    norm_q = normalize_query("FileMind 智能")
    results = retriever.search(norm_q, top_k=5)
    assert len(results) >= 1
    assert any(r["chunk_id"] == "c_mix1" for r in results)
