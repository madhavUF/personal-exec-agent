"""
Egress allowlist enforcement.

Default policy is strict local-first:
- allow localhost
- allow core model/API domains (Anthropic, Groq, OpenAI, Google APIs)
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


DEFAULT_ALLOWLIST = [
    "localhost",
    "127.0.0.1",
    "api.anthropic.com",
    "api.groq.com",
    "api.openai.com",
    "accounts.google.com",
    "oauth2.googleapis.com",
    "googleapis.com",
    "smartdevicemanagement.googleapis.com",
]


def _load_allowlist() -> list[str]:
    raw = os.getenv("EGRESS_ALLOWLIST", "").strip()
    if not raw:
        return DEFAULT_ALLOWLIST
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _hardening_enabled() -> bool:
    return os.getenv("SECURITY_HARDENING", "false").strip().lower() in {"1", "true", "yes", "on"}


def host_allowed(host: str) -> bool:
    if not _hardening_enabled():
        return True
    host = (host or "").lower().strip()
    if not host:
        return False
    allowlist = _load_allowlist()
    for allowed in allowlist:
        if host == allowed:
            return True
        if allowed.startswith(".") and host.endswith(allowed):
            return True
        if allowed and host.endswith("." + allowed):
            return True
    return False


def ensure_allowed_url(url: str) -> None:
    if not _hardening_enabled():
        return
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host_allowed(host):
        raise PermissionError(f"Egress blocked by allowlist policy for host: {host}")


def allow_public_web_research() -> bool:
    if not _hardening_enabled():
        return True
    return os.getenv("ALLOW_PUBLIC_WEB_RESEARCH", "false").strip().lower() in {"1", "true", "yes", "on"}

