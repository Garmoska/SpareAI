"""Bearer-token auth dependency factory."""
from __future__ import annotations

from fastapi import Header, HTTPException, status


def bearer_dependency(expected_token: str):
    """Build a FastAPI dependency that enforces `Authorization: Bearer <expected>`.

    Returns 401 with a generic payload — never reveals which token was wrong.
    """

    async def _check(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "unauthorized"})
        token = authorization.split(" ", 1)[1].strip()
        # Constant-time-ish compare; token values are short in PoC so impact is negligible.
        if not _consteq(token, expected_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail={"error": "unauthorized"})

    return _check


def _consteq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= ord(x) ^ ord(y)
    return r == 0
