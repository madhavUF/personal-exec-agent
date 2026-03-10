"""
Security helpers:
- Redaction for logs/errors
- Safe logging wrappers that avoid leaking secrets
"""

from __future__ import annotations

import logging
import re
from typing import Any

LOGGER = logging.getLogger("personal_agent")

_SECRET_PATTERNS = [
    # API key-like values
    re.compile(r"(sk-[A-Za-z0-9_\-]+)"),
    re.compile(r"(gsk_[A-Za-z0-9]+)"),
    re.compile(r"(AIza[0-9A-Za-z\-_]+)"),
    re.compile(r"((?:GOCSPX|GOOGLE|ya29\.)[A-Za-z0-9\-_\.]+)"),
    # Authorization/Bearer
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)(x-agent-key\s*:\s*)[^\s]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,]+"),
]

_SENSITIVE_KEYS = {
    "authorization",
    "x-agent-key",
    "x-approval-key",
    "x-approval-totp",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "anthropic_api_key",
    "groq_api_key",
    "openai_api_key",
    "google_client_secret",
    "body",  # avoid logging raw email/message body
    "content",
}


def redact_text(value: str) -> str:
    redacted = value
    for pat in _SECRET_PATTERNS:
        redacted = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "***REDACTED***", redacted)
    return redacted


def redact_obj(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(data, list):
        return [redact_obj(v) for v in data]
    if isinstance(data, str):
        return redact_text(data)
    return data


def safe_error_message(err: Exception | str) -> str:
    return redact_text(str(err))


def safe_log(level: int, message: str, payload: Any | None = None) -> None:
    if payload is None:
        LOGGER.log(level, redact_text(message))
    else:
        LOGGER.log(level, "%s | %s", redact_text(message), redact_obj(payload))

