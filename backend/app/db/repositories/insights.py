"""Document insights and folder insights repository operations."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InsightRepository:
    """Provides strongly typed CRUD queries for document and folder insights."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_document_insight(
        self, file_id: str, model_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieves the cached document insight for a file."""
        if model_name:
            cursor = self.conn.execute(
                """
                SELECT * FROM document_insights
                WHERE file_id = ? AND model_name = ?
                LIMIT 1;
                """,
                (file_id, model_name),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT * FROM document_insights
                WHERE file_id = ?
                ORDER BY updated_at DESC
                LIMIT 1;
                """,
                (file_id,),
            )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["structural_summary"] = json.loads(d.get("structural_summary_json") or "{}")
        except Exception:
            d["structural_summary"] = {}
        try:
            d["key_topics"] = json.loads(d.get("key_topics_json") or "[]")
        except Exception:
            d["key_topics"] = []
        try:
            d["key_decisions"] = json.loads(d.get("key_decisions_json") or "[]")
        except Exception:
            d["key_decisions"] = []
        try:
            d["citations"] = json.loads(d.get("citations_json") or "[]")
        except Exception:
            d["citations"] = []
        return d

    def get_document_insights_by_files(
        self, file_ids: List[str], model_name: Optional[str] = None, chunk_size: int = 500
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieves cached document insights mapped by file_id for a list of file_ids with parameter batching."""
        if not file_ids:
            return {}
        unique_file_ids = list(dict.fromkeys(file_ids))
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(unique_file_ids), chunk_size):
            batch = unique_file_ids[i:i + chunk_size]
            placeholders = ",".join("?" * len(batch))
            if model_name:
                cursor = self.conn.execute(
                    f"SELECT * FROM document_insights WHERE file_id IN ({placeholders}) AND model_name = ?;",
                    (*batch, model_name),
                )
            else:
                cursor = self.conn.execute(
                    f"SELECT * FROM document_insights WHERE file_id IN ({placeholders}) ORDER BY updated_at DESC;",
                    batch,
                )
            for row in cursor.fetchall():
                fid = row["file_id"]
                if not model_name and fid in out:
                    continue
                d = dict(row)
                try:
                    d["structural_summary"] = json.loads(d.get("structural_summary_json") or "{}")
                except Exception:
                    d["structural_summary"] = {}
                try:
                    d["key_topics"] = json.loads(d.get("key_topics_json") or "[]")
                except Exception:
                    d["key_topics"] = []
                try:
                    d["key_decisions"] = json.loads(d.get("key_decisions_json") or "[]")
                except Exception:
                    d["key_decisions"] = []
                try:
                    d["citations"] = json.loads(d.get("citations_json") or "[]")
                except Exception:
                    d["citations"] = []
                out[fid] = d
        return out

    def upsert_document_insight(
        self,
        file_id: str,
        status: str,
        content_hash: str,
        parser_version: str,
        chunker_version: str,
        model_provider: str,
        model_name: str,
        model_tag: Optional[str] = None,
        structural_summary: Optional[Dict[str, Any]] = None,
        executive_summary: Optional[str] = None,
        key_topics: Optional[List[str]] = None,
        key_decisions: Optional[List[str]] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None,
        insight_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inserts or updates a document insight record for a file and model."""
        now = _utcnow_iso()
        iid = insight_id or str(uuid.uuid4())
        struct_json = json.dumps(structural_summary or {})
        topics_json = json.dumps(key_topics or [])
        decisions_json = json.dumps(key_decisions or [])
        citations_json = json.dumps(citations or [])

        query = """
        INSERT INTO document_insights (
            insight_id, file_id, status, content_hash, parser_version, chunker_version,
            model_provider, model_name, model_tag, structural_summary_json,
            executive_summary, key_topics_json, key_decisions_json, citations_json,
            error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id, model_name) DO UPDATE SET
            status = excluded.status,
            content_hash = excluded.content_hash,
            parser_version = excluded.parser_version,
            chunker_version = excluded.chunker_version,
            model_provider = excluded.model_provider,
            model_tag = excluded.model_tag,
            structural_summary_json = excluded.structural_summary_json,
            executive_summary = excluded.executive_summary,
            key_topics_json = excluded.key_topics_json,
            key_decisions_json = excluded.key_decisions_json,
            citations_json = excluded.citations_json,
            error = excluded.error,
            updated_at = excluded.updated_at
        RETURNING *;
        """
        cursor = self.conn.execute(
            query,
            (
                iid,
                file_id,
                status,
                content_hash,
                parser_version,
                chunker_version,
                model_provider,
                model_name,
                model_tag,
                struct_json,
                executive_summary,
                topics_json,
                decisions_json,
                citations_json,
                error,
                now,
                now,
            ),
        )
        row = cursor.fetchone()
        d = dict(row)
        try:
            d["structural_summary"] = json.loads(d.get("structural_summary_json") or "{}")
        except Exception:
            d["structural_summary"] = {}
        try:
            d["key_topics"] = json.loads(d.get("key_topics_json") or "[]")
        except Exception:
            d["key_topics"] = []
        try:
            d["key_decisions"] = json.loads(d.get("key_decisions_json") or "[]")
        except Exception:
            d["key_decisions"] = []
        try:
            d["citations"] = json.loads(d.get("citations_json") or "[]")
        except Exception:
            d["citations"] = []
        return d

    def delete_document_insight(self, file_id: str) -> bool:
        """Deletes all document insights for a file."""
        cursor = self.conn.execute(
            "DELETE FROM document_insights WHERE file_id = ?;", (file_id,)
        )
        return cursor.rowcount > 0

    def get_folder_insight(
        self, folder_id: str, model_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieves the cached folder insight for a folder."""
        if model_name:
            cursor = self.conn.execute(
                """
                SELECT * FROM folder_insights
                WHERE folder_id = ? AND model_name = ?
                LIMIT 1;
                """,
                (folder_id, model_name),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT * FROM folder_insights
                WHERE folder_id = ?
                ORDER BY updated_at DESC
                LIMIT 1;
                """,
                (folder_id,),
            )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["structural_summary"] = json.loads(d.get("structural_summary_json") or "{}")
        except Exception:
            d["structural_summary"] = {}
        try:
            d["key_themes"] = json.loads(d.get("key_themes_json") or "[]")
        except Exception:
            d["key_themes"] = []
        try:
            d["key_decisions"] = json.loads(d.get("key_decisions_json") or "[]")
        except Exception:
            d["key_decisions"] = []
        try:
            d["citations"] = json.loads(d.get("citations_json") or "[]")
        except Exception:
            d["citations"] = []
        return d

    def upsert_folder_insight(
        self,
        folder_id: str,
        status: str,
        composite_hash: str,
        model_provider: str,
        model_name: str,
        model_tag: Optional[str] = None,
        structural_summary: Optional[Dict[str, Any]] = None,
        executive_summary: Optional[str] = None,
        key_themes: Optional[List[str]] = None,
        key_decisions: Optional[List[str]] = None,
        citations: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None,
        insight_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inserts or updates a folder insight record for a folder and model."""
        now = _utcnow_iso()
        iid = insight_id or str(uuid.uuid4())
        struct_json = json.dumps(structural_summary or {})
        themes_json = json.dumps(key_themes or [])
        decisions_json = json.dumps(key_decisions or [])
        citations_json = json.dumps(citations or [])

        query = """
        INSERT INTO folder_insights (
            insight_id, folder_id, status, composite_hash,
            model_provider, model_name, model_tag, structural_summary_json,
            executive_summary, key_themes_json, key_decisions_json, citations_json,
            error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder_id, model_name) DO UPDATE SET
            status = excluded.status,
            composite_hash = excluded.composite_hash,
            model_provider = excluded.model_provider,
            model_tag = excluded.model_tag,
            structural_summary_json = excluded.structural_summary_json,
            executive_summary = excluded.executive_summary,
            key_themes_json = excluded.key_themes_json,
            key_decisions_json = excluded.key_decisions_json,
            citations_json = excluded.citations_json,
            error = excluded.error,
            updated_at = excluded.updated_at
        RETURNING *;
        """
        cursor = self.conn.execute(
            query,
            (
                iid,
                folder_id,
                status,
                composite_hash,
                model_provider,
                model_name,
                model_tag,
                struct_json,
                executive_summary,
                themes_json,
                decisions_json,
                citations_json,
                error,
                now,
                now,
            ),
        )
        row = cursor.fetchone()
        d = dict(row)
        try:
            d["structural_summary"] = json.loads(d.get("structural_summary_json") or "{}")
        except Exception:
            d["structural_summary"] = {}
        try:
            d["key_themes"] = json.loads(d.get("key_themes_json") or "[]")
        except Exception:
            d["key_themes"] = []
        try:
            d["key_decisions"] = json.loads(d.get("key_decisions_json") or "[]")
        except Exception:
            d["key_decisions"] = []
        try:
            d["citations"] = json.loads(d.get("citations_json") or "[]")
        except Exception:
            d["citations"] = []
        return d

    def delete_folder_insight(self, folder_id: str) -> bool:
        """Deletes all folder insights for a folder."""
        cursor = self.conn.execute(
            "DELETE FROM folder_insights WHERE folder_id = ?;", (folder_id,)
        )
        return cursor.rowcount > 0
