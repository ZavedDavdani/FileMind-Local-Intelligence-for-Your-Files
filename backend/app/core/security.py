"""Path validation, normalization, and filesystem security checks."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class SecurityError(Exception):
    """Raised when a path fails security constraints (traversal, escape, symlink)."""
    pass


class SecurityForbiddenError(SecurityError):
    """Raised when a path is outside registered folders or contains symlinks/junctions."""
    pass


class SecurityNotFoundError(SecurityError):
    """Raised when a normalized path does not exist on disk."""
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


def contains_symlink_or_junction(target_path: str, root_path: Optional[str] = None) -> bool:
    """Checks whether target_path or any parent directory (up to root_path) is a symlink or junction."""
    try:
        norm_target = normalize_path(target_path)
        curr = Path(norm_target)
        norm_root = normalize_path(root_path) if root_path else None

        while True:
            if is_symlink_or_junction(str(curr)):
                return True
            if norm_root and os.path.normcase(str(curr)) == os.path.normcase(norm_root):
                break
            parent = curr.parent
            if parent == curr:
                break
            curr = parent
    except Exception:
        pass
    return False


def paths_overlap(path_a: str, path_b: str) -> bool:
    """Returns True if path_a equals path_b, path_a is a subpath of path_b, or path_b is a subpath of path_a."""
    try:
        norm_a = normalize_path(path_a)
        norm_b = normalize_path(path_b)

        # 1. Exact canonical or case-insensitive match
        if norm_a == norm_b or os.path.normcase(norm_a) == os.path.normcase(norm_b):
            return True

        # 2. Check if a is inside b or b is inside a
        if is_path_within_root(norm_a, norm_b) or is_path_within_root(norm_b, norm_a):
            return True

        return False
    except Exception:
        return False


def find_overlapping_path(candidate_path: str, existing_paths: List[str]) -> Optional[str]:
    """Finds the first existing path that overlaps with candidate_path, or None."""
    for existing in existing_paths:
        if paths_overlap(candidate_path, existing):
            return existing
    return None


def resolve_and_authorize(
    target_path_input: str, registered_folders: List[Union[Dict[str, Any], str]]
) -> Tuple[str, str]:
    """Validates, normalizes, and authorizes a target path against registered FileMind folders.

    Enforces:
      1. Non-empty string and normalization (SecurityError if invalid/null-byte)
      2. Path existence on disk (SecurityNotFoundError if missing)
      3. Registered folder containment (SecurityForbiddenError if outside all registered folders)
      4. Symlink and junction rejection (SecurityForbiddenError if target or parent is symlink/junction)

    Returns:
      (canonical_target_path, matched_root_folder_path)
    """
    target_path = normalize_path(target_path_input)

    if not os.path.exists(target_path):
        raise SecurityNotFoundError(f"Target path does not exist: {target_path}")

    matched_rf_path = None
    for rf in registered_folders:
        rf_path = rf if isinstance(rf, str) else rf.get("path", "")
        if not rf_path:
            continue
        try:
            if is_path_within_root(target_path, rf_path):
                matched_rf_path = normalize_path(rf_path)
                break
        except Exception:
            continue

    if not matched_rf_path:
        raise SecurityForbiddenError("Access denied: target path is outside all registered FileMind folders.")

    if is_symlink_or_junction(target_path) or contains_symlink_or_junction(target_path, matched_rf_path):
        raise SecurityForbiddenError("Access denied: symlinks and junctions are not permitted for filesystem actions.")

    return target_path, matched_rf_path
