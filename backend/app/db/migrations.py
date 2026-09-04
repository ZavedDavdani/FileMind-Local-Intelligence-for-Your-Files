"""Version-aware, safe SQLite schema migrations."""

import sqlite3
from typing import List, Tuple

SCHEMA_VERSION = 9


MIGRATION_V1_SQL = """
-- Schema migrations tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- Registered folders table
CREATE TABLE IF NOT EXISTS folders (
    folder_id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1,
    integrity_mode TEXT NOT NULL DEFAULT 'NORMAL' CHECK (integrity_mode IN ('NORMAL', 'STRICT')),
    indexing_enabled INTEGER NOT NULL DEFAULT 1,
    exclude_patterns TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Discovered and indexed files table
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER NOT NULL,
    modified_at TEXT NOT NULL,
    created_at TEXT,
    last_seen_at TEXT DEFAULT (datetime('now')),
    sha256 TEXT,
    index_status TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK (index_status IN ('DISCOVERED', 'QUEUED', 'PROCESSING', 'INDEXED', 'FAILED', 'SKIPPED', 'MISSING')),
    indexing_error TEXT,
    indexed_at TEXT,
    FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE
);

-- Indexing job queue table
CREATE TABLE IF NOT EXISTS indexing_jobs (
    job_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'METADATA_DISCOVERY' CHECK (job_type IN ('METADATA_DISCOVERY', 'HASH_VERIFICATION', 'DOCUMENT_PARSE', 'CHUNK_GENERATION', 'DELETE_CLEANUP')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    retry_at TEXT,
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE
);

-- Normalized filesystem event audit log
CREATE TABLE IF NOT EXISTS file_events (
    event_id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    file_id TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('CREATE', 'MODIFY', 'DELETE', 'MOVE', 'RENAME', 'SCAN_ERROR')),
    path TEXT NOT NULL,
    old_path TEXT,
    observed_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT,
    processing_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (processing_status IN ('PENDING', 'PROCESSED', 'IGNORED', 'FAILED')),
    FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_files_folder_id ON files(folder_id);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(index_status);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_jobs_status_retry ON indexing_jobs(status, retry_at, priority DESC);
CREATE INDEX IF NOT EXISTS idx_events_folder_time ON file_events(folder_id, observed_at DESC);
"""

MIGRATION_V2_SQL = """
-- Phase 2: Document Chunks and Provenance Table
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_path TEXT NOT NULL,
    page INTEGER,
    section TEXT,
    h1_parent TEXT,
    h2_parent TEXT,
    line_start INTEGER,
    line_end INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    content_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text',
    token_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
);

-- Chunks Performance Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_h1_parent ON chunks(h1_parent);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(page);
CREATE INDEX IF NOT EXISTS idx_chunks_file_index ON chunks(file_id, chunk_index);
"""

MIGRATION_V3_SQL = """
-- Phase 3: Lexical Retrieval (SQLite FTS5) Table & Triggers
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    h1_parent,
    h2_parent,
    section,
    source_file,
    chunk_id UNINDEXED,
    file_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to maintain FTS5 synchronized with chunks table
CREATE TRIGGER IF NOT EXISTS trg_chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, content, h1_parent, h2_parent, section, source_file, chunk_id, file_id)
    VALUES (new.rowid, new.content, COALESCE(new.h1_parent, ''), COALESCE(new.h2_parent, ''), COALESCE(new.section, ''), new.source_file, new.chunk_id, new.file_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
    INSERT INTO chunks_fts (rowid, content, h1_parent, h2_parent, section, source_file, chunk_id, file_id)
    VALUES (new.rowid, new.content, COALESCE(new.h1_parent, ''), COALESCE(new.h2_parent, ''), COALESCE(new.section, ''), new.source_file, new.chunk_id, new.file_id);
END;

-- Populate existing rows if any (delete first to ensure idempotency)
DELETE FROM chunks_fts;
INSERT INTO chunks_fts (rowid, content, h1_parent, h2_parent, section, source_file, chunk_id, file_id)
SELECT rowid, content, COALESCE(h1_parent, ''), COALESCE(h2_parent, ''), COALESCE(section, ''), source_file, chunk_id, file_id FROM chunks;
"""

MIGRATION_V4_SQL = """
-- Phase 3 trigger hardening: Ensure FTS5 delete/update triggers use standard DELETE syntax
DROP TRIGGER IF EXISTS trg_chunks_ad;
DROP TRIGGER IF EXISTS trg_chunks_au;

CREATE TRIGGER IF NOT EXISTS trg_chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE rowid = old.rowid;
    INSERT INTO chunks_fts (rowid, content, h1_parent, h2_parent, section, source_file, chunk_id, file_id)
    VALUES (new.rowid, new.content, COALESCE(new.h1_parent, ''), COALESCE(new.h2_parent, ''), COALESCE(new.section, ''), new.source_file, new.chunk_id, new.file_id);
END;
"""

MIGRATION_V5_SQL = """
-- Phase 3 Hardening: Embedding Index Metadata & Provenance tracking
CREATE TABLE IF NOT EXISTS embedding_index_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    config_json TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

MIGRATION_V6_SQL = """
-- Phase 5.5: Document Insights & Grounded Second Brain Understanding
CREATE TABLE IF NOT EXISTS document_insights (
    insight_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('NOT_GENERATED', 'GENERATING', 'READY', 'STALE', 'MODEL_UNAVAILABLE', 'FAILED')),
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    model_provider TEXT NOT NULL DEFAULT 'ollama',
    model_name TEXT NOT NULL,
    model_tag TEXT,
    structural_summary_json TEXT DEFAULT '{}',
    executive_summary TEXT,
    key_topics_json TEXT DEFAULT '[]',
    key_decisions_json TEXT DEFAULT '[]',
    citations_json TEXT DEFAULT '[]',
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
    UNIQUE(file_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_doc_insights_file_id ON document_insights(file_id);
CREATE INDEX IF NOT EXISTS idx_doc_insights_status ON document_insights(status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_doc_insights_file_model ON document_insights(file_id, model_name);
"""

MIGRATION_V7_SQL = """
-- Phase 5.5: Folder Insights & Grounded Folder-Level Understanding
CREATE TABLE IF NOT EXISTS folder_insights (
    insight_id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('NOT_GENERATED', 'GENERATING', 'READY', 'STALE', 'MODEL_UNAVAILABLE', 'FAILED', 'NO_EVIDENCE')),
    composite_hash TEXT NOT NULL,
    model_provider TEXT NOT NULL DEFAULT 'ollama',
    model_name TEXT NOT NULL,
    model_tag TEXT,
    structural_summary_json TEXT DEFAULT '{}',
    executive_summary TEXT,

    key_themes_json TEXT DEFAULT '[]',
    key_decisions_json TEXT DEFAULT '[]',
    citations_json TEXT DEFAULT '[]',
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE,
    UNIQUE(folder_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_folder_insights_folder_id ON folder_insights(folder_id);
CREATE INDEX IF NOT EXISTS idx_folder_insights_status ON folder_insights(status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_folder_insights_folder_model ON folder_insights(folder_id, model_name);
"""

MIGRATION_V8_SQL = """
-- Phase 6: Expand file_events event_type to include SCAN_ERROR
CREATE TABLE IF NOT EXISTS file_events_new (
    event_id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    file_id TEXT,
    event_type TEXT NOT NULL CHECK (event_type IN ('CREATE', 'MODIFY', 'DELETE', 'MOVE', 'RENAME', 'SCAN_ERROR')),
    path TEXT NOT NULL,
    old_path TEXT,
    observed_at TEXT DEFAULT (datetime('now')),
    processed_at TEXT,
    processing_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (processing_status IN ('PENDING', 'PROCESSED', 'IGNORED', 'FAILED')),
    FOREIGN KEY (folder_id) REFERENCES folders(folder_id) ON DELETE CASCADE
);
INSERT INTO file_events_new (event_id, folder_id, file_id, event_type, path, old_path, observed_at, processed_at, processing_status)
SELECT event_id, folder_id, file_id, event_type, path, old_path, observed_at, processed_at, processing_status FROM file_events;
DROP TABLE file_events;
ALTER TABLE file_events_new RENAME TO file_events;
CREATE INDEX IF NOT EXISTS idx_events_folder_time ON file_events(folder_id, observed_at DESC);
"""

MIGRATION_V9_SQL = """
-- Phase 6 Performance: Files FTS5 index and query performance indexes
CREATE INDEX IF NOT EXISTS idx_files_modified_at ON files(modified_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_folder_status ON files(folder_id, index_status);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename,
    relative_path,
    sha256,
    file_id UNINDEXED,
    tokenize='trigram'
);

-- Triggers to maintain files_fts synchronized with files table
CREATE TRIGGER IF NOT EXISTS trg_files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts (rowid, filename, relative_path, sha256, file_id)
    VALUES (new.rowid, new.filename, new.relative_path, COALESCE(new.sha256, ''), new.file_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_files_ad AFTER DELETE ON files BEGIN
    DELETE FROM files_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS trg_files_au AFTER UPDATE ON files BEGIN
    DELETE FROM files_fts WHERE rowid = old.rowid;
    INSERT INTO files_fts (rowid, filename, relative_path, sha256, file_id)
    VALUES (new.rowid, new.filename, new.relative_path, COALESCE(new.sha256, ''), new.file_id);
END;

-- Backfill existing rows if any (delete first to ensure idempotency)
DELETE FROM files_fts;
INSERT INTO files_fts (rowid, filename, relative_path, sha256, file_id)
SELECT rowid, filename, relative_path, COALESCE(sha256, ''), file_id FROM files;
"""


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Applies all pending database migrations in order."""
    cursor = conn.cursor()

    # Ensure migrations tracking table exists
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now'))
        );
        """
    )

    cursor.execute("SELECT MAX(version) FROM schema_migrations;")
    row = cursor.fetchone()
    current_version = row[0] if (row and row[0] is not None) else 0

    if current_version < 1:
        cursor.executescript(MIGRATION_V1_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (1);")
        current_version = 1

    if current_version < 2:
        cursor.executescript(MIGRATION_V2_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (2);")
        current_version = 2

    if current_version < 3:
        cursor.executescript(MIGRATION_V3_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (3);")
        current_version = 3

    if current_version < 4:
        cursor.executescript(MIGRATION_V4_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (4);")
        current_version = 4

    if current_version < 5:
        cursor.executescript(MIGRATION_V5_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (5);")
        current_version = 5

    if current_version < 6:
        cursor.executescript(MIGRATION_V6_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (6);")
        current_version = 6

    if current_version < 7:
        cursor.executescript(MIGRATION_V7_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (7);")
        current_version = 7

    if current_version < 8:
        cursor.executescript(MIGRATION_V8_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (8);")
        current_version = 8

    if current_version < 9:
        cursor.executescript(MIGRATION_V9_SQL)
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (9);")
        current_version = 9

    return current_version
