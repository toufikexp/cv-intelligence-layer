"""HMAC-SHA256 signing and verification for webhook payloads."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException


def sign_payload(payload: bytes, secret: str) -> str:
    """Create an HMAC-SHA256 signature for a webhook payload."""
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(provided: str, payload: bytes, secret: str) -> None:
    """Verify incoming webhook signature. Raises 401 on mismatch."""
    expected = sign_payload(payload, secret)
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
