from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.config import get_settings


async def get_api_key(authorization: str | None = Header(default=None)) -> str:
    """Validate Bearer API key.

    Args:
        authorization: `Authorization` header value.

    Returns:
        The validated API key.
    """

    if not authorization:
        raise HTTPException(status_code=401, detail={"detail": "Missing Authorization header", "code": "UNAUTHORIZED"})

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail={"detail": "Invalid auth scheme", "code": "UNAUTHORIZED"})

    token = parts[1].strip()
    if token != get_settings().app_api_key:
        raise HTTPException(status_code=403, detail={"detail": "Invalid API key", "code": "FORBIDDEN"})

    return token


AuthDep = Depends(get_api_key)

