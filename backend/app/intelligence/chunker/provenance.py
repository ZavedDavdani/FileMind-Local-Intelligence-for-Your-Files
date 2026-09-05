"""Provenance record definitions and builders."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ChunkProvenance:
    """Immutable provenance record attached to every chunk."""
    chunk_id: str
    file_id: str
    source_file: str
    source_path: str
    page: Optional[int] = None
    section: Optional[str] = None
    h1_parent: Optional[str] = None
    h2_parent: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    frame_index: Optional[int] = None
    media_type: str = "document"  # 'document', 'image', 'audio', 'video', 'tabular'
    extraction_method: Optional[str] = None  # 'native', 'ocr', 'vision_description', 'transcription', 'metadata'
    content_hash: str = ""
    chunk_index: int = 0
    parser_name: str = "unknown"
    parser_version: str = "unknown"
    chunker_version: str = "phase2-hierarchical-v2"

    content: str = ""
    content_type: str = "text"  # 'text', 'table', 'code'
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict, hash=False)

    def to_dict(self) -> Dict[str, Any]:
        """Converts chunk provenance to a serializable dictionary."""
        return asdict(self)
