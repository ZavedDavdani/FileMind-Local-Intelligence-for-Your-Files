"""Version-aware, safe SQLite schema migrations."""

import sqlite3
from typing import List, Tuple

SCHEMA_VERSION = 5


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
    event_type TEXT NOT NULL CHECK (event_type IN ('CREATE', 'MODIFY', 'DELETE', 'MOVE', 'RENAME')),
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

-- Populate existing rows if any
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

    return current_version


