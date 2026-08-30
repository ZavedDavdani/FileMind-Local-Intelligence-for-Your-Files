"""Path validation, normalization, and filesystem security checks."""

import os
from pathlib import Path
from typing import List, Optional


class SecurityError(Exception):
    """Raised when a path fails security constraints (traversal, escape, symlink)."""
    pass


def normalize_path(path_str: str) -> str:
    """Normalizes and canonicalizes a path string."""
    if not path_str or not isinstance(path_str, str):
        raise SecurityError("Path parameter cannot be empty")

    if "\x00" in path_str:
        raise SecurityError("Path contains null byte characters")

    # Resolve environment variables and user home
    expanded = os.path.expanduser(os.path.expandvars(path_str.strip()))
    # Absolute and normalized path
    norm = os.path.normpath(os.path.abspath(expanded))
    return norm


def is_symlink_or_junction(path_str: str) -> bool:
    """Detects whether a path is a symbolic link or Windows reparse point/junction."""
    try:
        p = Path(path_str)
        if p.is_symlink():
            return True
        
        # On Windows, check for FILE_ATTRIBUTE_REPARSE_POINT (0x400)
        if os.name == "nt" and os.path.exists(path_str):
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(p))
            if attrs != -1 and (attrs & 0x400):
                return True
    except Exception:
        pass
    return False


def is_path_within_root(target_path: str, root_path: str) -> bool:
    """Ensures target_path is strictly inside root_path without escaping."""
    norm_target = normalize_path(target_path)
    norm_root = normalize_path(root_path)

    # Fast equality check
    if norm_target == norm_root:
        return True

    try:
        # Check if root is a common prefix
        common = os.path.commonpath([norm_root, norm_target])
        if os.path.normcase(common) != os.path.normcase(norm_root):
            return False

        # Additional check with relative path
        rel = os.path.relpath(norm_target, norm_root)
        if rel.startswith("..") or rel == ".":
            return False

        # Verify realpath doesn't escape outside root due to symlinks/junctions
        real_target = os.path.realpath(norm_target)
        real_root = os.path.realpath(norm_root)
        real_common = os.path.commonpath([real_root, real_target])
        if os.path.normcase(real_common) != os.path.normcase(real_root):
            return False

        return True
    except Exception:
        return False


def validate_subpath_safety(target_path: str, root_path: str) -> str:
    """Validates that target_path is a valid child of root_path, raising SecurityError if not."""
    norm_target = normalize_path(target_path)
    norm_root = normalize_path(root_path)

    if not is_path_within_root(norm_target, norm_root):
        raise SecurityError(
            f"Path traversal or root escape detected: '{norm_target}' is outside root '{norm_root}'"
        )
    return norm_target
