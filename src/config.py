"""
Central configuration and paths for the Personal AI Agent.

Loads config.yaml from the project root and exposes paths and settings.
All paths are absolute. Falls back to defaults if config.yaml is missing.
"""

import os
from pathlib import Path

# Project root = directory containing config.yaml (parent of src/)
_THIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = _THIS_DIR.parent

_CONFIG = None
_CONFIG_PATH = PROJECT_DIR / "config.yaml"


def _load_config() -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    import yaml
    defaults = {
        "data": {"folder": "./my_data", "output": "./data"},
        "exclude": {
            "folders": [".git", "__pycache__", "node_modules"],
            "patterns": ["*.tmp", "*.log", ".DS_Store"],
        },
        "ocr": {"provider": "doctr", "min_text_threshold": 100},
        "chunking": {"chunk_size": 500, "overlap": 50},
        "embeddings": {"model": "all-MiniLM-L6-v2"},
        "vector_db": {"provider": "chromadb", "path": "./data/chroma_db", "collection": "personal_docs"},
        "search": {"top_k": 5, "min_similarity": 0.1, "semantic_weight": 0.7, "keyword_weight": 0.3},
        "llm": {"provider": "anthropic", "model": "claude-sonnet-4-20250514", "max_tokens": 1024},
        "privacy": {"show_sources": True, "log_queries": False},
        "api": {"upload_max_mb": 20},
    }

    if _CONFIG_PATH.is_file():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            for key, default in defaults.items():
                if key in loaded and isinstance(loaded[key], dict) and isinstance(default, dict):
                    for k, v in default.items():
                        if k not in loaded[key]:
                            loaded[key][k] = v
                elif key not in loaded:
                    loaded[key] = default
            _CONFIG = loaded
        except Exception:
            _CONFIG = defaults
    else:
        _CONFIG = defaults

    return _CONFIG


def get_config() -> dict:
    """Return full config dict (with defaults merged)."""
    return _load_config().copy()


def _resolve(path_spec: str) -> Path:
    """Resolve a path from config (relative to PROJECT_DIR) to absolute."""
    p = Path(path_spec)
    if not p.is_absolute():
        p = PROJECT_DIR / p
    return p.resolve()


# ---------------------------------------------------------------------------
# Paths (all absolute)
# ---------------------------------------------------------------------------

def get_data_folder() -> Path:
    return _resolve(_load_config()["data"]["folder"])


def get_output_dir() -> Path:
    return _resolve(_load_config()["data"]["output"])


def get_docs_path() -> Path:
    return get_output_dir() / "documents.json"


def get_chroma_path() -> Path:
    return _resolve(_load_config()["vector_db"]["path"])


def get_exclude_folders() -> list:
    return list(_load_config()["exclude"].get("folders", []))


def get_exclude_patterns() -> list:
    return list(_load_config()["exclude"].get("patterns", []))


def get_chunking() -> dict:
    return _load_config()["chunking"].copy()


def get_search_settings() -> dict:
    return _load_config()["search"].copy()


def get_embeddings_model() -> str:
    return _load_config()["embeddings"]["model"]


def get_vector_db_collection() -> str:
    return _load_config()["vector_db"].get("collection", "personal_docs")


def get_llm_settings() -> dict:
    return _load_config()["llm"].copy()


def get_ocr_min_text_threshold() -> int:
    return _load_config()["ocr"].get("min_text_threshold", 100)


def get_docs_path_str() -> str:
    """Return DOCS_PATH as string for code that expects str."""
    return str(get_docs_path())


def get_upload_max_bytes() -> int:
    """Max upload file size in bytes (default 20 MB)."""
    mb = _load_config().get("api", {}).get("upload_max_mb", 20)
    return mb * 1024 * 1024


def get_recruiter_resume_files() -> list[Path]:
    """Resume files for recruiter agent (resume-only context, separate from main RAG)."""
    files = _load_config().get("recruiter", {}).get("resume_files", ["my_data/resume.md"])
    return [_resolve(f) for f in files if _resolve(f).is_file()]
