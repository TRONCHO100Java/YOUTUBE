"""El liveness no debe depender de Postgres ni de Redis."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health_is_ok_without_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ClipForge"
    assert body["version"]


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/no-existe")
    assert response.status_code == 404
    assert "error" in response.json()
