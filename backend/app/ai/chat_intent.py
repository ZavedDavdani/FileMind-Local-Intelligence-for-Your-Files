"""
Deterministic Chat Intent Classifier & Handlers for FileMind.

Classifies incoming user messages into:
1. CONVERSATIONAL: Greetings, politeness, capabilities, and general assistance without requiring document evidence.
2. METADATA_INVENTORY: Questions about indexed files, folders, counts, sizes, and file properties answered directly from DB.
3. GROUNDED_CONTENT: Document-content questions, summaries, comparisons, and extraction requiring RAG retrieval.
"""

import enum
import re
from typing import Any, Dict, List, Optional
from app.db.repository import Repository


class ChatIntent(str, enum.Enum):
    CONVERSATIONAL = "CONVERSATIONAL"
    METADATA_INVENTORY = "METADATA_INVENTORY"
    GROUNDED_CONTENT = "GROUNDED_CONTENT"


# Regex patterns for deterministic classification
GREETINGS_PATTERN = re.compile(
    r"^(hi|hello|hey|hey\s+there|greetings|good\s+morning|good\s+afternoon|good\s+evening|howdy|hola|yo)[\s.!?,]*$",
    re.IGNORECASE,
)

CONVERSATIONAL_QUERIES_PATTERN = re.compile(
    r"(how\s+are\s+you|who\s+are\s+you|what\s+is\s+your\s+name|what\s+are\s+you|thanks|thank\s+you|bye|goodbye|cya|see\s+you|^help[\s.!?,]*$|what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|how\s+do\s+i\s+use\s+filemind|what\s+is\s+filemind|help\s+me(\s+understand)?|what\s+features\s+do\s+you\s+have)",
    re.IGNORECASE,
)

METADATA_INVENTORY_PATTERN = re.compile(
    r"(what\s+files\s+(do\s+i\s+have|are\s+indexed|have\s+been\s+indexed|are\s+in\s+this|are\s+there|are\s+in\s+the\s+index)|what\s+files\s+do\s+i\s+have\s+indexed|show\s+(me\s+)?(all\s+)?(my\s+)?(indexed\s+)?(files|documents)|list\s+(all\s+)?(my\s+)?(indexed\s+)?(files|documents)|what\s+are\s+all\s+the\s+files|tell\s+me\s+about\s+this\s+file|what\s+is\s+this\s+file|how\s+many\s+files(\s+are\s+indexed)?|what\s+folders(\s+are\s+indexed)?|which\s+folders(\s+are\s+being\s+indexed|\s+are\s+indexed)?|show\s+folders|list\s+folders)",
    re.IGNORECASE,
)


def classify_chat_intent(query: str) -> ChatIntent:
    """Classifies user chat prompt into CONVERSATIONAL, METADATA_INVENTORY, or GROUNDED_CONTENT."""
    clean_q = query.strip()
    if not clean_q:
        return ChatIntent.CONVERSATIONAL

    if GREETINGS_PATTERN.match(clean_q) or CONVERSATIONAL_QUERIES_PATTERN.search(clean_q):
        return ChatIntent.CONVERSATIONAL

    if METADATA_INVENTORY_PATTERN.search(clean_q):
        return ChatIntent.METADATA_INVENTORY

    return ChatIntent.GROUNDED_CONTENT


def format_conversational_response(query: str) -> str:
    """Generates an informative, polite conversational response explaining capabilities."""
    q_lower = query.lower().strip()

    if GREETINGS_PATTERN.match(q_lower):
        return (
            "Hello! I am **FileMind AI**, your local-first intelligent file assistant.\n\n"
            "I can help you search, summarize, analyze, and compare documents across your indexed folders and files. "
            "How can I assist you today?"
        )

    if "how are you" in q_lower:
        return (
            "I'm operating normally and ready to help! All local indexing and retrieval engines are active. "
            "What would you like to explore in your files?"
        )

    if "who are you" in q_lower or "what is your name" in q_lower or "what is filemind" in q_lower:
        return (
            "I am **FileMind AI**, a 100% private, local desktop intelligence assistant running on your Windows machine. "
            "I operate strictly on your local files with zero cloud uploads."
        )

    if "thank" in q_lower:
        return "You're very welcome! Let me know if you need anything else from your documents."

    if "bye" in q_lower or "goodbye" in q_lower:
        return "Goodbye! Have a great day. Feel free to return anytime you need help with your files."

    # Default capability / help overview
    return (
        "I am **FileMind AI**, your private local document intelligence assistant. Here is what I can do for you:\n\n"
        "1. **Search & Question Answering**: Ask questions across your documents (PDFs, Office docs, code, Markdown, spreadsheets, images with OCR, and audio/video transcripts).\n"
        "2. **Scoped Chat**: Focus our conversation on **All Files**, a specific **Folder**, or a single **File**.\n"
        "3. **File Inventory**: Ask *\"What files do I have?\"* or *\"Show indexed files\"* for a real-time summary.\n"
        "4. **Cross-File Intelligence**: Compare documents or extract key themes in the **Knowledge Workspace**.\n"
        "5. **Evidence & Provenance**: Every grounded answer links directly to verified citations with page numbers, line ranges, or media timestamps.\n\n"
        "To get started, ask a question about your indexed files or add folders in the **Files & Folders** tab!"
    )


def format_metadata_inventory_response(
    repo: Repository,
    scope_type: str = "ALL",
    scope_id: Optional[str] = None,
    query: str = "",
) -> str:
    """Generates a structured, accurate inventory report from the SQLite database."""
    if scope_type == "FILE" and scope_id:
        f = repo.get_file_by_id(scope_id)
        if not f:
            return f"The selected file (`{scope_id}`) could not be found in the index."
        
        chunks = repo.get_chunks_by_file(scope_id)
        size_kb = round(f["size_bytes"] / 1024, 1)
        return (
            f"### File Details: `{f['filename']}`\n\n"
            f"- **Path:** `{f['path']}`\n"
            f"- **Type / Extension:** `{f['extension']}` ({f.get('mime_type') or 'unknown'})\n"
            f"- **Size:** {size_kb} KB ({f['size_bytes']:,} bytes)\n"
            f"- **Indexing Status:** `{f['index_status']}`\n"
            f"- **Generated Chunks:** {len(chunks)} structural chunks\n"
            f"- **Last Modified:** {f['modified_at']}\n"
        )

    folders = repo.list_folders()
    if scope_type == "FOLDER" and scope_id:
        target_folder = repo.get_folder(scope_id)
        if not target_folder:
            return f"The selected folder (`{scope_id}`) could not be found."
        files = repo.list_files(folder_id=scope_id, limit=500)
        folder_label = f"Folder `{target_folder['path']}`"
    else:
        files = repo.list_files(limit=500)
        folder_label = "all registered folders"

    if not files:
        if not folders:
            return (
                "You do not have any registered folders or indexed files yet.\n\n"
                "Click **+ Add Folder** or **+ Add Files** in the **Files & Folders** tab to begin indexing."
            )
        return (
            f"There are currently no indexed files in {folder_label}.\n\n"
            "Files may still be queued or discovering. Check the **Files & Folders** tab for real-time progress."
        )

    # Group by extension
    ext_counts: Dict[str, int] = {}
    total_bytes = 0
    status_counts: Dict[str, int] = {}

    for f in files:
        ext = f["extension"].lower() or "no-ext"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        total_bytes += f.get("size_bytes", 0)
        st = f.get("index_status", "DISCOVERED")
        status_counts[st] = status_counts.get(st, 0) + 1

    total_mb = round(total_bytes / (1024 * 1024), 2)
    ext_summary = ", ".join(f"`{k}` ({v})" for k, v in sorted(ext_counts.items(), key=lambda x: -x[1])[:8])

    lines = [
        f"### Indexed Files Summary ({len(files)} total in {folder_label})",
        f"- **Total Storage Size:** {total_mb} MB",
        f"- **File Formats:** {ext_summary}",
        f"- **Index Status:** {status_counts.get('INDEXED', 0)} indexed, {status_counts.get('QUEUED', 0) + status_counts.get('PROCESSING', 0)} in progress, {status_counts.get('FAILED', 0)} failed",
        "",
        "**Tracked Files List (Top 25):**",
    ]

    for i, f in enumerate(files[:25], 1):
        size_str = f"{round(f['size_bytes']/1024, 1)} KB" if f['size_bytes'] < 1024*1024 else f"{round(f['size_bytes']/(1024*1024), 2)} MB"
        lines.append(f"{i}. `{f['filename']}` ({f['extension']}) — {size_str} — *[{f['index_status']}]*")

    if len(files) > 25:
        lines.append(f"\n*... and {len(files) - 25} more files.*")

    return "\n".join(lines)
