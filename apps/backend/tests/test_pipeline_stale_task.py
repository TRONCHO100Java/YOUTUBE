"""Una tarea reencolada no debe rehacer el trabajo de la que ya iba en camino.

Reencolar un proyecto que seguía en la cola dejaba dos mensajes para el mismo
vídeo: el worker descargaba, transcribía y renderizaba dos veces seguidas. El
proyecto guarda el id de su tarea vigente, y esa es la única fuente fiable de
quién manda.
"""

from __future__ import annotations

from clipforge.worker.tasks.pipeline import _task_is_stale


def test_the_task_the_project_points_at_is_the_one_that_runs() -> None:
    assert _task_is_stale("task-1", "task-1") is False


def test_an_older_task_steps_aside_for_the_one_that_replaced_it() -> None:
    assert _task_is_stale("task-2", "task-1") is True


def test_a_project_without_task_id_does_not_block_anything() -> None:
    """Un proyecto creado antes de que existiera el campo no bloquea su tarea."""
    assert _task_is_stale(None, "task-1") is False


def test_a_direct_call_without_task_id_always_runs() -> None:
    """Llamar a la tarea a mano (tests, consola) no tiene id con quien competir."""
    assert _task_is_stale("task-1", None) is False


def test_the_comparison_survives_a_non_string_task_id() -> None:
    """Celery entrega el id como str, pero un UUID no debe parecer otra tarea."""
    import uuid

    task_id = uuid.UUID("3a7c4d71-6410-4ed7-862f-c29f32d8b8c1")
    assert _task_is_stale(str(task_id), task_id) is False
