"""
FileMind Evidence, Search, and Conversation Export Service.

Supports:
- Formatted Markdown export with citation footnotes and document provenance.
- Clean JSON schema export for downstream tooling.
- Human-readable plain text transcript export.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ExportService:
    """Formats and exports conversations and knowledge evidence."""

    @staticmethod
    def export_conversation_markdown(
        conversation: Dict[str, Any],
        messages: List[Dict[str, Any]],
        include_citations: bool = True,
        include_timestamps: bool = True,
    ) -> str:
        """Formats a conversation into clean, publication-ready Markdown."""
        lines = [
            f"# FileMind Conversation: {conversation.get('title', 'Conversation')}",
            "",
            f"**Scope:** {conversation.get('scope_type', 'ALL')}" + (f" ({conversation.get('scope_id')})" if conversation.get('scope_id') else ""),
            f"**Exported At:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            "",
        ]

        for m in messages:
            role_name = "User" if m["role"] == "user" else "FileMind AI"
            ts_suffix = f" *({m.get('created_at', '')})*" if include_timestamps and m.get("created_at") else ""
            lines.append(f"### {role_name}{ts_suffix}")
            lines.append("")
            lines.append(m["content"])
            lines.append("")

            if include_citations and m.get("citations"):
                lines.append("**Sources & Evidence:**")
                for c in m["citations"]:
                    cid = c.get("citation_id", "E")
                    src = c.get("source_file", "document")
                    sec = f", Section: *{c.get('section')}*" if c.get("section") else ""
                    pg = f", Page {c.get('page')}" if c.get("page") else ""
                    lines.append(f"- **[{cid}]** `{src}`{pg}{sec}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def export_conversation_json(
        conversation: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        """Formats a conversation into structured JSON."""
        payload = {
            "conversation": conversation,
            "messages": messages,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "generator": "FileMind v0.1.0",
        }
        return json.dumps(payload, indent=2)

    @staticmethod
    def export_conversation_text(
        conversation: Dict[str, Any],
        messages: List[Dict[str, Any]],
    ) -> str:
        """Formats a conversation into plain text transcript."""
        lines = [
            f"FILEMIND CONVERSATION: {conversation.get('title', 'Conversation')}",
            f"Scope: {conversation.get('scope_type', 'ALL')}",
            f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "=" * 70,
            "",
        ]

        for m in messages:
            role = "USER" if m["role"] == "user" else "FILEMIND"
            lines.append(f"[{role}] ({m.get('created_at', '')})")
            lines.append(m["content"])
            lines.append("")
            if m.get("citations"):
                lines.append("  [SOURCES]")
                for c in m["citations"]:
                    lines.append(f"   * [{c.get('citation_id')}] {c.get('source_file')}")
                lines.append("")
            lines.append("-" * 50)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def export_search_markdown(query: str, results: List[Dict[str, Any]]) -> str:
        """Formats search results and evidence into Markdown."""
        lines = [
            f"# FileMind Search Evidence: \"{query}\"",
            f"**Total Results:** {len(results)}",
            f"**Exported At:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            "",
        ]

        for i, r in enumerate(results, 1):
            src = r.get("source_file") or r.get("filename") or "Unknown File"
            score = r.get("score")
            score_part = f"Score: {score:.3f}" if isinstance(score, (int, float)) else "Unranked"
            sec = f" | Section: *{r.get('section')}*" if r.get("section") else ""
            pg = f" | Page {r.get('page')}" if r.get("page") else ""
            lines.append(f"### {i}. `{src}` ({score_part}{sec}{pg})")
            lines.append("")
            lines.append(f"> {r.get('snippet') or r.get('content', '')}")
            lines.append("")

        return "\n".join(lines)
