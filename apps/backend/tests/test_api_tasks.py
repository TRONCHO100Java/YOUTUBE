"""Estado de las tareas encoladas.

Es lo que separa "no ha pasado nada" de "está tardando". Sin esto, un botón
que encola trabajo devuelve 200 y el usuario no vuelve a saber nada.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from clipforge.api.routers import tasks as tasks_module

TASK_ID = "3a7c4d71-6410-4ed7-862f-c29f32d8b8c1"


class _FakeResult:
    def __init__(self, state: str, result: Any = None) -> None:
        self.state = state
        self.result = result


@pytest.fixture
def celery_result(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Sustituye el backend de resultados por uno que dice lo que se le pida."""

    def install(state: str, result: Any = None) -> None:
        class _FakeApp:
            def AsyncResult(self, task_id: str) -> _FakeResult:
                return _FakeResult(state, result)

        module = type(tasks_module)("clipforge.worker.celery_app")
        module.celery_app = _FakeApp()  # type: ignore[attr-defined]
        monkeypatch.setitem(__import__("sys").modules, "clipforge.worker.celery_app", module)

    return install


async def test_a_task_still_running_is_not_ready(client: AsyncClient, celery_result: Any) -> None:
    celery_result("STARTED")

    body = (await client.get(f"/api/tasks/{TASK_ID}")).json()

    assert body["ready"] is False
    assert body["successful"] is None


async def test_a_queued_task_reads_as_not_ready_either(
    client: AsyncClient, celery_result: Any
) -> None:
    """PENDING es ambiguo en Celery, y para quien espera las dos son 'todavía no'."""
    celery_result("PENDING")

    body = (await client.get(f"/api/tasks/{TASK_ID}")).json()

    assert body["state"] == "PENDING"
    assert body["ready"] is False


async def test_a_finished_task_carries_what_it_returned(
    client: AsyncClient, celery_result: Any
) -> None:
    celery_result("SUCCESS", {"retitled": 5})

    body = (await client.get(f"/api/tasks/{TASK_ID}")).json()

    assert body["ready"] is True
    assert body["successful"] is True
    assert body["result"] == {"retitled": 5}
    assert body["error"] is None


async def test_a_failed_task_says_why_without_the_traceback(
    client: AsyncClient, celery_result: Any
) -> None:
    celery_result("FAILURE", RuntimeError("Ollama no responde"))

    body = (await client.get(f"/api/tasks/{TASK_ID}")).json()

    assert body["ready"] is True
    assert body["successful"] is False
    assert body["error"] == "Ollama no responde"
    assert body["result"] is None


async def test_a_task_that_returned_something_odd_does_not_break_the_contract(
    client: AsyncClient, celery_result: Any
) -> None:
    """El contrato promete un objeto; una lista no lo es y no se propaga."""
    celery_result("SUCCESS", ["algo", "raro"])

    body = (await client.get(f"/api/tasks/{TASK_ID}")).json()

    assert body["successful"] is True
    assert body["result"] is None


async def test_an_id_that_is_not_a_task_id_is_rejected(client: AsyncClient) -> None:
    """Los ids los genera Celery y son UUID: cualquier otra cosa es una clave suelta."""
    response = await client.get("/api/tasks/../../etc/passwd")

    assert response.status_code in (404, 422)
