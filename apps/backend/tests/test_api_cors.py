"""Cabeceras CORS expuestas al navegador.

`allow_headers` cubre las cabeceras de PETICIÓN; estas son de RESPUESTA y hay
que declararlas aparte. Sin `Content-Range` la etiqueta `<video>` no puede
resolver el tamaño del fichero y se queda cargando indefinidamente — que es
exactamente lo que pasó al probar el reproductor.
"""

from __future__ import annotations

from httpx import AsyncClient

ORIGIN = "http://localhost:3000"


async def test_range_headers_are_exposed_to_the_browser(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": ORIGIN})

    exposed = {
        value.strip().lower()
        for value in response.headers.get("access-control-expose-headers", "").split(",")
    }
    assert "content-range" in exposed
    assert "accept-ranges" in exposed


async def test_content_disposition_is_exposed(client: AsyncClient) -> None:
    """Sin exponerla, la descarga pierde el nombre del clip."""
    response = await client.get("/health", headers={"Origin": ORIGIN})

    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert "content-disposition" in exposed


async def test_preflight_is_allowed_from_the_frontend(client: AsyncClient) -> None:
    response = await client.options(
        "/api/projects",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
