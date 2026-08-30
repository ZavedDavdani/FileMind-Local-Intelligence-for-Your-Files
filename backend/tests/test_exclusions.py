"""Exclusion rules test suite: Default noise filters and custom glob patterns."""

import pytest
from app.core.exclusions import ExclusionMatcher


def test_default_directory_exclusions():
    matcher = ExclusionMatcher()
    assert matcher.is_directory_excluded(".git") is True
    assert matcher.is_directory_excluded("node_modules") is True
    assert matcher.is_directory_excluded("__pycache__") is True
    assert matcher.is_directory_excluded("venv") is True
    assert matcher.is_directory_excluded(".venv") is True
    assert matcher.is_directory_excluded("dist") is True
    assert matcher.is_directory_excluded("build") is True
    assert matcher.is_directory_excluded(".cache") is True
    assert matcher.is_directory_excluded("temp") is True


def test_default_allowed_directories():
    matcher = ExclusionMatcher()
    assert matcher.is_directory_excluded("src") is False
    assert matcher.is_directory_excluded("documents") is False
    assert matcher.is_directory_excluded("projects") is False


def test_default_file_exclusions():
    matcher = ExclusionMatcher()
    assert matcher.is_file_excluded("cache.tmp") is True
    assert matcher.is_file_excluded("debug.log") is True
    assert matcher.is_file_excluded("~$document.docx") is True
    assert matcher.is_file_excluded(".DS_Store") is True
    assert matcher.is_file_excluded("desktop.ini") is True


def test_default_allowed_files():
    matcher = ExclusionMatcher()
    assert matcher.is_file_excluded("report.pdf") is False
    assert matcher.is_file_excluded("notes.md") is False
    assert matcher.is_file_excluded("main.py") is False
    assert matcher.is_file_excluded("data.csv") is False


def test_custom_user_exclusion_patterns():
    matcher = ExclusionMatcher(custom_patterns=["*.bak", "secrets/*", "drafts"])
    assert matcher.is_file_excluded("old_config.bak") is True
    assert matcher.is_directory_excluded("drafts") is True
    assert matcher.is_file_excluded("api.key", rel_path="secrets/api.key") is True
    assert matcher.is_file_excluded("normal.txt") is False


def test_nested_path_exclusion():
    matcher = ExclusionMatcher()
    # File inside an excluded directory path
    assert matcher.is_file_excluded("index.js", rel_path="node_modules/react/index.js") is True
    assert matcher.is_file_excluded("HEAD", rel_path=".git/HEAD") is True
    # File in normal nested directory
    assert matcher.is_file_excluded("index.js", rel_path="src/components/index.js") is False
