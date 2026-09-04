"""Parser registry managing document parser discovery and instantiation with deferred lazy-loading."""

import os
from typing import Callable, Dict, List, Optional, Union
from app.intelligence.parsers.base import BaseParser


class ParserRegistry:
    """Central registry mapping file extensions and MIME types to document parsers with deferred initialization."""

    def __init__(self):
        self._parsers_by_ext: Dict[str, Union[BaseParser, Callable[[], BaseParser]]] = {}
        self._parsers_by_mime: Dict[str, Union[BaseParser, Callable[[], BaseParser]]] = {}
        self._registered_parsers: List[BaseParser] = []

    def register_factory(
        self,
        factory: Callable[[], BaseParser],
        extensions: List[str],
        mime_types: List[str],
        allow_overwrite: bool = True,
    ):
        """Registers a deferred parser factory function for specified extensions and MIME types."""
        for ext in extensions:
            ext_clean = ext.lower()
            if not allow_overwrite and ext_clean in self._parsers_by_ext:
                raise ValueError(f"Extension '{ext_clean}' is already registered to another parser.")
            self._parsers_by_ext[ext_clean] = factory
        for mime in mime_types:
            mime_clean = mime.lower()
            if not allow_overwrite and mime_clean in self._parsers_by_mime:
                raise ValueError(f"MIME type '{mime_clean}' is already registered to another parser.")
            self._parsers_by_mime[mime_clean] = factory

    def register_parser(self, parser: BaseParser, allow_overwrite: bool = True):
        """Registers an already instantiated parser instance."""
        for ext in parser.supported_extensions:
            ext_clean = ext.lower()
            if not allow_overwrite and ext_clean in self._parsers_by_ext:
                raise ValueError(f"Extension '{ext_clean}' is already registered to another parser.")
        for mime in parser.supported_mime_types:
            mime_clean = mime.lower()
            if not allow_overwrite and mime_clean in self._parsers_by_mime:
                raise ValueError(f"MIME type '{mime_clean}' is already registered to another parser.")

        if parser not in self._registered_parsers:
            self._registered_parsers.append(parser)
        for ext in parser.supported_extensions:
            self._parsers_by_ext[ext.lower()] = parser
        for mime in parser.supported_mime_types:
            self._parsers_by_mime[mime.lower()] = parser

    def get_parser_for_file(self, file_path: str, mime_type: Optional[str] = None) -> Optional[BaseParser]:
        """Resolves the appropriate parser for a given file path and optional MIME type."""
        ext = os.path.splitext(file_path)[1].lower()
        entry = self._parsers_by_ext.get(ext)
        if not entry and mime_type:
            entry = self._parsers_by_mime.get(mime_type.lower())

        if entry is None:
            return None

        if callable(entry):
            factory = entry
            parser = factory()
            if parser not in self._registered_parsers:
                self._registered_parsers.append(parser)
            for e, f in list(self._parsers_by_ext.items()):
                if f is factory:
                    self._parsers_by_ext[e] = parser
            for m, f in list(self._parsers_by_mime.items()):
                if f is factory:
                    self._parsers_by_mime[m] = parser
            for e in parser.supported_extensions:
                self._parsers_by_ext[e.lower()] = parser
            for m in parser.supported_mime_types:
                self._parsers_by_mime[m.lower()] = parser
            return parser

        return entry

    def list_registered_parsers(self) -> List[BaseParser]:
        """Returns all registered parser instances, initializing all deferred parsers if needed."""
        for ext, entry in list(self._parsers_by_ext.items()):
            if callable(entry):
                factory = entry
                p = factory()
                if p not in self._registered_parsers:
                    self._registered_parsers.append(p)
                for e, f in list(self._parsers_by_ext.items()):
                    if f is factory:
                        self._parsers_by_ext[e] = p
                for m, f in list(self._parsers_by_mime.items()):
                    if f is factory:
                        self._parsers_by_mime[m] = p
                for e in p.supported_extensions:
                    self._parsers_by_ext[e.lower()] = p
                for m in p.supported_mime_types:
                    self._parsers_by_mime[m.lower()] = p
        return list(self._registered_parsers)


def _get_pdf_parser():
    from app.intelligence.parsers.pdf_parser import PyMuPDFParser
    return PyMuPDFParser()


def _get_docx_parser():
    from app.intelligence.parsers.docx_parser import DocxParser
    return DocxParser()


def _get_pptx_parser():
    from app.intelligence.parsers.pptx_parser import PptxParser
    return PptxParser()


def _get_text_parser():
    from app.intelligence.parsers.text_parser import TextAndCodeParser
    return TextAndCodeParser()


def _get_tabular_parser():
    from app.intelligence.parsers.tabular_parser import TabularParser
    return TabularParser()


# Global default registry with deferred lazy loading
default_parser_registry = ParserRegistry()
default_parser_registry.register_factory(_get_pdf_parser, [".pdf"], ["application/pdf"])
default_parser_registry.register_factory(_get_docx_parser, [".docx"], ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"])
default_parser_registry.register_factory(_get_pptx_parser, [".pptx"], ["application/vnd.openxmlformats-officedocument.presentationml.presentation"])
default_parser_registry.register_factory(
    _get_text_parser,
    [".txt", ".md", ".py", ".rs", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".sql", ".sh", ".bat", ".ps1", ".c", ".cpp", ".h", ".hpp", ".go", ".java"],
    ["text/plain", "text/markdown", "text/x-python", "application/javascript", "text/html", "text/css", "application/json", "application/xml"],
)
default_parser_registry.register_factory(
    _get_tabular_parser,
    [".csv", ".tsv", ".xlsx"],
    ["text/csv", "text/tab-separated-values", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
)
