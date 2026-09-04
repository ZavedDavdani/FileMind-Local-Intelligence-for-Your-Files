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
