"""
TOTP authentication helpers for approval actions.
Compatible with authenticator apps (including Duo Mobile TOTP accounts).
"""

from __future__ import annotations

import os


def has_totp_secret() -> bool:
    return bool(os.getenv("APPROVAL_TOTP_SECRET", "").strip())


def verify_totp_code(code: str, valid_window: int = 1) -> bool:
    """
    Verify a 6-digit (or compatible) TOTP code.
    valid_window=1 allows +/- one 30s time step to reduce clock skew issues.
    """
    secret = os.getenv("APPROVAL_TOTP_SECRET", "").strip()
    if not secret:
        return False
    if not code:
        return False
    try:
        import pyotp

        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code.strip(), valid_window=valid_window))
    except Exception:
        return False


def build_totp_uri(account_name: str = "personal-agent", issuer_name: str = "Personal AI Agent") -> str:
    """
    Returns otpauth URI you can add to an authenticator app.
    """
    secret = os.getenv("APPROVAL_TOTP_SECRET", "").strip()
    if not secret:
        return ""
    try:
        import pyotp

        return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer_name)
    except Exception:
        return ""

