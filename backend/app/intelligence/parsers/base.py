"""Abstract base class for document parsers."""

from abc import ABC, abstractmethod
from typing import List, Optional
from app.intelligence.models import Document


class DocumentParserError(Exception):
    """Base exception for document parsing failures."""
    pass


class EncryptedDocumentError(DocumentParserError):
    """Raised when a document is encrypted/password protected."""
    pass


class UnsupportedFormatError(DocumentParserError):
    """Raised when the document format is not supported."""
    pass


class CorruptedDocumentError(DocumentParserError):
    """Raised when the document file is corrupted or unreadable."""
    pass


class BaseParser(ABC):
    """Abstract interface for all document format parsers."""

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Unique identifier for this parser (e.g. 'pymupdf-parser')."""
        pass

    @property
    @abstractmethod
    def parser_version(self) -> str:
        """Version string of the parser."""
        pass

    @property
    @abstractmethod
    def supported_mime_types(self) -> List[str]:
        """List of MIME types handled by this parser."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """List of file extensions (with leading dot) handled by this parser."""
        pass

    @abstractmethod
    def parse(self, file_path: str, file_id: str, mime_type: str) -> Document:
        """
        Parses a file into the normalized Document representation.
        
        Args:
            file_path: Absolute validated path to the file.
            file_id: FileMind unique file identifier.
            mime_type: Detected MIME type of the file.
            
        Returns:
            Document: Normalized document instance.
            
        Raises:
            DocumentParserError, EncryptedDocumentError, CorruptedDocumentError
        """
        pass
