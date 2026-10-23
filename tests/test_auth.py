from __future__ import annotations

import pytest
from fastapi import HTTPException

from spareai.common.auth import bearer_dependency


@pytest.mark.asyncio
async def test_accepts_valid_bearer():
    dep = bearer_dependency("secret")
    await dep(authorization="Bearer secret")  # must not raise


@pytest.mark.asyncio
async def test_rejects_missing_header():
    dep = bearer_dependency("secret")
    with pytest.raises(HTTPException) as exc:
        await dep(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_wrong_token():
    dep = bearer_dependency("secret")
    with pytest.raises(HTTPException) as exc:
        await dep(authorization="Bearer nope")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_wrong_scheme():
    dep = bearer_dependency("secret")
    with pytest.raises(HTTPException) as exc:
        await dep(authorization="Basic c2VjcmV0")
    assert exc.value.status_code == 401
