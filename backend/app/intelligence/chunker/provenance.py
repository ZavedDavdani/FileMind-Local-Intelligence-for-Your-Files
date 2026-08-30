"""Provenance record definitions and builders."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
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
    content_hash: str = ""
    chunk_index: int = 0
    parser_name: str = "unknown"
    parser_version: str = "1.0.0"
    chunker_version: str = "phase2-hierarchical-v1"
    content: str = ""
    content_type: str = "text"  # 'text', 'table', 'code'
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts chunk provenance to a serializable dictionary."""
        return asdict(self)
