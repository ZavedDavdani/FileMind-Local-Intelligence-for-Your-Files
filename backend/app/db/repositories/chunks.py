"""Document chunks, provenance, and embedding metadata repository operations."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.intelligence.chunker.hierarchical import CHUNKER_VERSION


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChunkRepository:
    """Provides strongly typed CRUD queries for document chunks and vector metadata."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def replace_file_chunks(self, file_id: str, chunks: List[Any]) -> int:
        """
        Atomically replaces all chunks for a given file_id.
        Removes any stale active chunks and inserts newly generated chunks.
        """
        self.conn.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
        now = _utcnow_iso()

        insert_sql = """
        INSERT INTO chunks (
            chunk_id, file_id, source_file, source_path, page, section,
            h1_parent, h2_parent, line_start, line_end, char_start, char_end,
            content_hash, chunk_index, parser_name, parser_version,
            chunker_version, content, content_type, token_count, metadata_json,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        );
        """
        MULTIMODAL_KEYS = (
            "sheet_name",
            "slide_number",
            "time_start",
            "time_end",
            "frame_index",
            "media_type",
            "extraction_method",
        )
        rows_to_insert = []
        for c in chunks:
            c_dict = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else c.__dict__)
            meta = dict(c_dict.get("metadata", {}) or {})
            for k in MULTIMODAL_KEYS:
                val = c_dict.get(k)
                if val is not None and k not in meta:
                    meta[k] = val
            meta_json = json.dumps(meta)
            rows_to_insert.append((
                c_dict["chunk_id"],
                file_id,
                c_dict.get("source_file", "unknown"),
                c_dict.get("source_path", ""),
                c_dict.get("page"),
                c_dict.get("section"),
                c_dict.get("h1_parent"),
                c_dict.get("h2_parent"),
                c_dict.get("line_start"),
                c_dict.get("line_end"),
                c_dict.get("char_start"),
                c_dict.get("char_end"),
                c_dict.get("content_hash", ""),
                c_dict.get("chunk_index", 0),
                c_dict.get("parser_name", "unknown"),
                c_dict.get("parser_version", "unknown"),
                c_dict.get("chunker_version", CHUNKER_VERSION),
                c_dict["content"],
                c_dict.get("content_type", "text"),
                c_dict.get("token_count", 0),
                meta_json,
                now,
                now,
            ))

        if rows_to_insert:
            self.conn.executemany(insert_sql, rows_to_insert)

        return len(rows_to_insert)

    @staticmethod
    def _hydrate_chunk_row(d: Dict[str, Any]) -> Dict[str, Any]:
        """Parses metadata_json and hydrates multimodal provenance fields."""
        try:
            meta = json.loads(d.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        d["metadata"] = meta
        for k in ("sheet_name", "slide_number", "time_start", "time_end", "frame_index", "media_type", "extraction_method"):
            if k in meta and d.get(k) is None:
                d[k] = meta[k]
        if "media_type" not in d or not d["media_type"]:
            d["media_type"] = "document"
        return d

    def get_chunks_by_file(self, file_id: str) -> List[Dict[str, Any]]:
        """Retrieves all chunks for a file ordered by chunk_index."""
        cursor = self.conn.execute(
            "SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC;",
            (file_id,),
        )
        results = []
        for row in cursor.fetchall():
            results.append(self._hydrate_chunk_row(dict(row)))
        return results

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single chunk by chunk_id."""
        cursor = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?;", (chunk_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._hydrate_chunk_row(dict(row))

    def get_chunks_by_files(self, file_ids: List[str], chunk_size: int = 500) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieves chunks grouped by file_id for a list of file_ids with parameter batching."""
        if not file_ids:
            return {}
        unique_file_ids = list(dict.fromkeys(file_ids))
        out: Dict[str, List[Dict[str, Any]]] = {}
        for i in range(0, len(unique_file_ids), chunk_size):
            batch = unique_file_ids[i:i + chunk_size]
            placeholders = ",".join("?" * len(batch))
            cursor = self.conn.execute(
                f"SELECT * FROM chunks WHERE file_id IN ({placeholders}) ORDER BY file_id, chunk_index ASC;",
                batch,
            )
            for row in cursor.fetchall():
                d = self._hydrate_chunk_row(dict(row))
                out.setdefault(d["file_id"], []).append(d)
        return out

    def get_chunks_by_ids(self, chunk_ids: List[str], chunk_size: int = 500) -> Dict[str, Dict[str, Any]]:
        """Retrieves chunks mapped by chunk_id for a list of chunk_ids with parameter batching."""
        if not chunk_ids:
            return {}
        unique_chunk_ids = list(dict.fromkeys(chunk_ids))
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(unique_chunk_ids), chunk_size):
            batch = unique_chunk_ids[i:i + chunk_size]
            placeholders = ",".join("?" * len(batch))
            cursor = self.conn.execute(
                f"SELECT * FROM chunks WHERE chunk_id IN ({placeholders});",
                batch,
            )
            for row in cursor.fetchall():
                d = self._hydrate_chunk_row(dict(row))
                out[d["chunk_id"]] = d
        return out

    def delete_chunks_by_file(self, file_id: str) -> int:
        """Explicitly deletes all chunks associated with a file_id."""
        cursor = self.conn.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
        return cursor.rowcount

    def count_total_chunks(self) -> int:
        """Returns the total number of chunks across all files."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM chunks;")
        return cursor.fetchone()[0]

    def count_chunks_by_folder(self, folder_id: str) -> int:
        """Returns the total number of chunks in a registered folder."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE file_id IN (SELECT file_id FROM files WHERE folder_id = ?);",
            (folder_id,),
        )
        return cursor.fetchone()[0]

    def get_document_intelligence_stats(self) -> Dict[str, Any]:
        """Returns summary statistics for Document Intelligence."""
        total_chunks = self.count_total_chunks()
        cursor = self.conn.execute(
            "SELECT index_status, COUNT(*) as cnt FROM files GROUP BY index_status;"
        )
        file_counts = {}
        for r in cursor.fetchall():
            file_counts[r["index_status"]] = r["cnt"]

        # Count files that have chunks
        cursor2 = self.conn.execute("SELECT COUNT(DISTINCT file_id) FROM chunks;")
        files_with_chunks = cursor2.fetchone()[0]

        return {
            "total_chunks": total_chunks,
            "files_with_chunks": files_with_chunks,
            "indexed_files": file_counts.get("INDEXED", 0),
            "queued_files": file_counts.get("QUEUED", 0),
            "failed_files": file_counts.get("FAILED", 0),
            "skipped_files": file_counts.get("SKIPPED", 0),
        }

    def get_file_chunk_versions(self, file_id: str) -> Optional[Dict[str, str]]:
        """Returns the parser_name, parser_version, and chunker_version of indexed chunks for a file."""
        cursor = self.conn.execute(
            """
            SELECT parser_name, parser_version, chunker_version
            FROM chunks
            WHERE file_id = ?
            LIMIT 1;
            """,
            (file_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "parser_name": row["parser_name"],
            "parser_version": row["parser_version"],
            "chunker_version": row["chunker_version"],
        }

    def get_embedding_metadata(self) -> Optional[Dict[str, Any]]:
        """Returns the recorded active embedding model identity from database."""
        cursor = self.conn.execute(
            """
            SELECT provider, model_name, model_version, dimension, config_json, updated_at
            FROM embedding_index_metadata
            WHERE id = 1;
            """
        )
        row = cursor.fetchone()
        if not row:
            return None
        config = {}
        try:
            config = json.loads(row["config_json"] or "{}")
        except Exception:
            pass
        return {
            "provider": row["provider"],
            "model_name": row["model_name"],
            "model_version": row["model_version"],
            "dimension": row["dimension"],
            "config": config,
            "updated_at": row["updated_at"],
        }

    def set_embedding_metadata(
        self,
        provider: str,
        model_name: str,
        model_version: str,
        dimension: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Sets or replaces the active embedding model identity."""
        config_json = json.dumps(config or {})
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO embedding_index_metadata
            (id, provider, model_name, model_version, dimension, config_json, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?);
            """,
            (provider, model_name, model_version, dimension, config_json, now),
        )
