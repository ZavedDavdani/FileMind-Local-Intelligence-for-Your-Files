"""Security test suite: Path traversal, root escapes, and reparse points."""

import os
import tempfile
import pytest
from app.core.security import (
    SecurityError,
    is_path_within_root,
    is_symlink_or_junction,
    normalize_path,
    validate_subpath_safety,
)


def test_normalize_path_basic():
    path = normalize_path("C:/dev/FileMind/backend")
    assert os.path.isabs(path)
    assert not path.endswith("/")
    assert not path.endswith("\\")


def test_normalize_path_rejects_null_bytes():
    with pytest.raises(SecurityError, match="null byte"):
        normalize_path("C:/dev/FileMind/\x00malicious")


def test_normalize_path_rejects_empty():
    with pytest.raises(SecurityError, match="empty"):
        normalize_path("")


def test_is_path_within_root_valid_children():
    with tempfile.TemporaryDirectory() as root:
        child_file = os.path.join(root, "docs", "file.txt")
        assert is_path_within_root(child_file, root) is True
        assert is_path_within_root(root, root) is True


def test_is_path_within_root_traversal_attempts():
    with tempfile.TemporaryDirectory() as root:
        # Relative traversal
        escape_path = os.path.join(root, "..", "secret.txt")
        assert is_path_within_root(escape_path, root) is False

        # Nested relative traversal
        nested_escape = os.path.join(root, "sub", "..", "..", "escape.txt")
        assert is_path_within_root(nested_escape, root) is False

        # Completely outside root
        outside = os.path.abspath(r"C:\Windows\System32\cmd.exe")
        assert is_path_within_root(outside, root) is False


def test_validate_subpath_safety_raises_on_escape():
    with tempfile.TemporaryDirectory() as root:
        escape_path = os.path.join(root, "..", "passwords.txt")
        with pytest.raises(SecurityError, match="outside root"):
            validate_subpath_safety(escape_path, root)
