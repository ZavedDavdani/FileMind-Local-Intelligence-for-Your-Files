"""Tests for app.core.security resolve_and_authorize function."""

import os
from unittest import mock
import pytest

from app.core.security import (
    resolve_and_authorize,
    SecurityError,
    SecurityForbiddenError,
    SecurityNotFoundError,
)


def test_resolve_and_authorize_valid_path(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    file_path = os.path.join(root_dir, "doc.txt")
    with open(file_path, "w") as f:
        f.write("test content")

    registered = [{"path": root_dir}]
    target, matched = resolve_and_authorize(file_path, registered)
    assert os.path.normcase(target) == os.path.normcase(file_path)
    assert os.path.normcase(matched) == os.path.normcase(root_dir)


def test_resolve_and_authorize_outside_path(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    outside_dir = str(tmp_path / "outside_root")
    os.makedirs(outside_dir, exist_ok=True)
    outside_file = os.path.join(outside_dir, "secret.txt")
    with open(outside_file, "w") as f:
        f.write("secret")

    registered = [{"path": root_dir}]
    with pytest.raises(SecurityForbiddenError) as exc:
        resolve_and_authorize(outside_file, registered)
    assert "outside all registered" in str(exc.value)


def test_resolve_and_authorize_nonexistent_path(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    missing_file = os.path.join(root_dir, "missing.txt")

    registered = [{"path": root_dir}]
    with pytest.raises(SecurityNotFoundError) as exc:
        resolve_and_authorize(missing_file, registered)
    assert "Target path does not exist" in str(exc.value)


def test_resolve_and_authorize_symlink_rejected(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    file_path = os.path.join(root_dir, "doc.txt")
    with open(file_path, "w") as f:
        f.write("test content")

    registered = [{"path": root_dir}]
    with mock.patch("app.core.security.is_symlink_or_junction", return_value=True):
        with pytest.raises(SecurityForbiddenError) as exc:
            resolve_and_authorize(file_path, registered)
        assert "symlinks and junctions" in str(exc.value)


def test_resolve_and_authorize_nested_path(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    nested_dir = os.path.join(root_dir, "sub", "deep")
    os.makedirs(nested_dir, exist_ok=True)
    file_path = os.path.join(nested_dir, "nested_doc.txt")
    with open(file_path, "w") as f:
        f.write("nested content")

    registered = [{"path": root_dir}]
    target, matched = resolve_and_authorize(file_path, registered)
    assert os.path.normcase(target) == os.path.normcase(file_path)
    assert os.path.normcase(matched) == os.path.normcase(root_dir)


def test_resolve_and_authorize_traversal_escape(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    secret_dir = str(tmp_path / "secret_folder")
    os.makedirs(secret_dir, exist_ok=True)
    secret_file = os.path.join(secret_dir, "secret.txt")
    with open(secret_file, "w") as f:
        f.write("top secret")

    traversal_path = os.path.join(root_dir, "..", "secret_folder", "secret.txt")
    registered = [{"path": root_dir}]

    with pytest.raises(SecurityForbiddenError) as exc:
        resolve_and_authorize(traversal_path, registered)
    assert "outside all registered" in str(exc.value)


def test_resolve_and_authorize_junction_parent_rejected(tmp_path):
    root_dir = str(tmp_path / "valid_root")
    os.makedirs(root_dir, exist_ok=True)
    file_path = os.path.join(root_dir, "doc.txt")
    with open(file_path, "w") as f:
        f.write("content")

    registered = [{"path": root_dir}]
    with mock.patch("app.core.security.contains_symlink_or_junction", return_value=True):
        with pytest.raises(SecurityForbiddenError) as exc:
            resolve_and_authorize(file_path, registered)
        assert "symlinks and junctions" in str(exc.value)


def test_resolve_and_authorize_null_byte_or_empty():
    with pytest.raises(SecurityError) as exc:
        resolve_and_authorize("", [{"path": "C:/some/path"}])
    assert "cannot be empty" in str(exc.value)

    with pytest.raises(SecurityError) as exc:
        resolve_and_authorize("C:/valid/path\x00extra", [{"path": "C:/valid"}])
    assert "null byte" in str(exc.value)


def test_resolve_and_authorize_case_insensitivity_on_windows(tmp_path):
    root_dir = str(tmp_path / "Valid_Root")
    os.makedirs(root_dir, exist_ok=True)
    file_path = os.path.join(root_dir, "Test_File.txt")
    with open(file_path, "w") as f:
        f.write("content")

    lower_file_path = file_path.lower()
    registered = [{"path": root_dir.lower()}]

    target, matched = resolve_and_authorize(lower_file_path, registered)
    assert os.path.normcase(target) == os.path.normcase(lower_file_path)
    assert os.path.normcase(matched) == os.path.normcase(root_dir.lower())
