"""Persistent conversations and chat messages repository operations."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatRepository:
    """Provides strongly typed CRUD queries for persistent conversations and chat messages."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_conversation(
        self,
        title: str,
        scope_type: str = "ALL",
        scope_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a new persistent conversation."""
        cid = conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
        now = _utcnow_iso()
        valid_scope = scope_type if scope_type in ("ALL", "FOLDER", "FILE") else "ALL"

        self.conn.execute(
            """
            INSERT INTO conversations (conversation_id, title, scope_type, scope_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (cid, title.strip() or "New Conversation", valid_scope, scope_id, now, now),
        )
        return self.get_conversation(cid)  # type: ignore

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single conversation by ID with message count."""
        cursor = self.conn.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.conversation_id) as message_count,
                   (SELECT m.content FROM chat_messages m WHERE m.conversation_id = c.conversation_id ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1) as last_message
            FROM conversations c
            WHERE c.conversation_id = ?;
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def list_conversations(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Lists conversations sorted by most recently updated."""
        cursor = self.conn.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.conversation_id) as message_count,
                   (SELECT m.content FROM chat_messages m WHERE m.conversation_id = c.conversation_id ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1) as last_message
            FROM conversations c
            ORDER BY c.updated_at DESC, c.conversation_id DESC
            LIMIT ? OFFSET ?;
            """,
            (limit, offset),
        )
        return [dict(r) for r in cursor.fetchall()]

    def update_conversation_title(self, conversation_id: str, title: str) -> Optional[Dict[str, Any]]:
        """Updates the conversation title and touch timestamp."""
        now = _utcnow_iso()
        self.conn.execute(
            """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE conversation_id = ?;
            """,
            (title.strip(), now, conversation_id),
        )
        return self.get_conversation(conversation_id)

    def touch_conversation(self, conversation_id: str) -> None:
        """Updates the updated_at timestamp of a conversation."""
        now = _utcnow_iso()
        self.conn.execute(
            """
            UPDATE conversations
            SET updated_at = ?
            WHERE conversation_id = ?;
            """,
            (now, conversation_id),
        )

    def delete_conversation(self, conversation_id: str) -> bool:
        """Deletes a conversation and cascades to its messages."""
        cursor = self.conn.execute(
            """
            DELETE FROM conversations WHERE conversation_id = ?;
            """,
            (conversation_id,),
        )
        return cursor.rowcount > 0

    def add_chat_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        evidence_status: Optional[str] = None,
        generation_status: Optional[str] = None,
        model_identity: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Appends a new message to a conversation."""
        mid = message_id or f"msg_{uuid.uuid4().hex[:12]}"
        now = _utcnow_iso()
        citations_json = json.dumps(citations or [])
        model_identity_json = json.dumps(model_identity or {})

        self.conn.execute(
            """
            INSERT INTO chat_messages (
                message_id, conversation_id, role, content, citations,
                evidence_status, generation_status, model_identity, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                mid,
                conversation_id,
                role,
                content,
                citations_json,
                evidence_status,
                generation_status,
                model_identity_json,
                now,
            ),
        )
        self.touch_conversation(conversation_id)

        return {
            "message_id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "evidence_status": evidence_status,
            "generation_status": generation_status,
            "model_identity": model_identity or {},
            "created_at": now,
        }

    def list_chat_messages(
        self, conversation_id: str, limit: int = 200, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Lists chat messages in deterministic chronological order for a conversation."""
        cursor = self.conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC, message_id ASC
            LIMIT ? OFFSET ?;
            """,
            (conversation_id, limit, offset),
        )
        messages = []
        for r in cursor.fetchall():
            d = dict(r)
            try:
                d["citations"] = json.loads(d.get("citations") or "[]")
            except Exception:
                d["citations"] = []
            try:
                d["model_identity"] = json.loads(d.get("model_identity") or "{}")
            except Exception:
                d["model_identity"] = {}
            messages.append(d)
        return messages

    def delete_chat_message(self, message_id: str) -> bool:
        """Deletes a single message by ID."""
        cursor = self.conn.execute(
            "DELETE FROM chat_messages WHERE message_id = ?;", (message_id,)
        )
        return cursor.rowcount > 0
