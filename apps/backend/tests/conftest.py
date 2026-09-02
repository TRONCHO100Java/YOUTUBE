"""Fixtures compartidas de test."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from clipforge.api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app en memoria (sin levantar uvicorn)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
