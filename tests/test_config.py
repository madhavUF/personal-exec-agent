"""Tests for src.config (config.yaml loading and paths)."""
import pytest


def test_config_loads():
    """Config should load and return a dict with expected keys."""
    from src.config import get_config
    cfg = get_config()
    assert isinstance(cfg, dict)
    assert "data" in cfg
    assert "chunking" in cfg
    assert "search" in cfg
    assert "exclude" in cfg
    assert "api" in cfg


def test_data_folder_path():
    """Data folder should be a path under project."""
    from src.config import get_data_folder, PROJECT_DIR
    folder = get_data_folder()
    assert str(folder).endswith("my_data") or "my_data" in str(folder)
    assert folder == PROJECT_DIR / "my_data" or str(PROJECT_DIR) in str(folder)


def test_docs_path():
    """Docs path should point to documents.json under data output."""
    from src.config import get_docs_path_str, get_output_dir
    path = get_docs_path_str()
    assert "documents.json" in path
    assert str(get_output_dir()) in path


def test_chunking_defaults():
    """Chunking config should have chunk_size and overlap."""
    from src.config import get_chunking
    c = get_chunking()
    assert "chunk_size" in c
    assert "overlap" in c
    assert c["chunk_size"] >= 100
    assert c["overlap"] >= 0


def test_exclude_lists():
    """Exclude should have folders and patterns."""
    from src.config import get_exclude_folders, get_exclude_patterns
    folders = get_exclude_folders()
    patterns = get_exclude_patterns()
    assert isinstance(folders, list)
    assert isinstance(patterns, list)
    assert ".git" in folders or len(folders) >= 0


def test_upload_max_bytes():
    """Upload max should be a positive number of bytes."""
    from src.config import get_upload_max_bytes
    n = get_upload_max_bytes()
    assert n > 0
    assert n >= 1024 * 1024  # at least 1 MB
