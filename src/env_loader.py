"""
Centralized environment loading.

- Loads `.env` from project root for non-sensitive app settings.
- Loads a separate credentials file for secrets (default: credentials/.secrets.env).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.config import PROJECT_DIR


def load_env() -> None:
    """
    Load runtime environment variables.
    Secrets file overrides .env values when both are present.
    """
    env_path = PROJECT_DIR / ".env"
    load_dotenv(env_path, override=False)
    creds_path = os.getenv("CREDENTIALS_FILE", str(PROJECT_DIR / "credentials" / ".secrets.env"))
    if os.path.exists(creds_path):
        load_dotenv(creds_path, override=True)

