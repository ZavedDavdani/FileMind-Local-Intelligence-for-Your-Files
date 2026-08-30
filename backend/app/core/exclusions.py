"""Exclusion rules and glob pattern matching for filesystem filtering."""

import os
import fnmatch
from pathlib import Path
from typing import List, Set

# Locked default high-noise exclusions per specification
DEFAULT_EXCLUDE_DIR_NAMES: Set[str] = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    ".cache",
    "temp",
    ".tmp",
    ".idea",
    ".vscode",
    "$recycle.bin",
    "system volume information",
}

DEFAULT_EXCLUDE_FILE_PATTERNS: List[str] = [
    "*.tmp",
    "*.temp",
    "*.log",
    "*.swp",
    "*.bak",
    "~$*",  # Office temporary lock files
    "desktop.ini",
    "thumbs.db",
    ".ds_store",
]


class ExclusionMatcher:
    """Evaluates whether paths, directory names, or filenames match exclusion rules."""

    def __init__(self, custom_patterns: List[str] = None):
        self.custom_patterns: List[str] = [p.strip() for p in (custom_patterns or []) if p.strip()]
        # Precompile lowercase sets and patterns for Windows case-insensitivity
        self.exact_dir_names: Set[str] = set(DEFAULT_EXCLUDE_DIR_NAMES)
        self.file_patterns: List[str] = list(DEFAULT_EXCLUDE_FILE_PATTERNS)

        for p in self.custom_patterns:
            cleaned = p.rstrip("/\\")
            if "/" not in cleaned and "\\" not in cleaned and "*" not in cleaned and "?" not in cleaned:
                self.exact_dir_names.add(cleaned.lower())
            else:
                self.file_patterns.append(p)

    def is_directory_excluded(self, dir_name: str, rel_path: str = "") -> bool:
        """Checks if a directory should be skipped entirely from traversal."""
        name_lower = dir_name.lower().rstrip("/\\")
        if name_lower in self.exact_dir_names:
            return True

        # Check glob matches against dirname
        for pat in self.file_patterns:
            pat_clean = pat.rstrip("/\\")
            if fnmatch.fnmatch(name_lower, pat_clean.lower()):
                return True

        # Check relative path if provided
        if rel_path:
            norm_rel = rel_path.replace("\\", "/").lower().strip("/")
            parts = norm_rel.split("/")
            for part in parts:
                if part in self.exact_dir_names:
                    return True
            for pat in self.file_patterns:
                pat_clean = pat.rstrip("/\\").lower()
                if fnmatch.fnmatch(norm_rel, pat_clean) or fnmatch.fnmatch(f"{norm_rel}/", pat_clean):
                    return True

        return False

    def is_file_excluded(self, file_name: str, rel_path: str = "") -> bool:
        """Checks if a specific file should be excluded from indexing."""
        name_lower = file_name.lower()

        # Check if any parent directory in rel_path is excluded
        if rel_path:
            norm_rel = rel_path.replace("\\", "/").lower()
            parts = norm_rel.split("/")[:-1]  # Parent directory components
            for part in parts:
                if part in self.exact_dir_names:
                    return True

        # Check file patterns
        for pat in self.file_patterns:
            pat_lower = pat.lower()
            if fnmatch.fnmatch(name_lower, pat_lower):
                return True
            if rel_path and fnmatch.fnmatch(rel_path.replace("\\", "/").lower(), pat_lower):
                return True

        return False
