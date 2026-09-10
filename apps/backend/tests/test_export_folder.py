"""La carpeta de exportacion es la bandeja de subida de un canal.

Con un solo canal daba igual como se llamase la carpeta. Con tres a la vez ya
no: agrupar por video obliga a entrar en ocho carpetas para subir a tres
canales, y agrupar por canal es el orden en el que de verdad se trabaja.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from clipforge.worker.tasks.pipeline import _export_folder_name

CHANNEL = UUID("2f5a1c9e-3d47-4b80-9a12-6e8c07b4d5f1")


class _Project:
    """Lo justo que mira la funcion: un titulo y un destino."""

    def __init__(self, title: str, publish_channel_id: UUID | None) -> None:
        self.title = title
        self.publish_channel_id = publish_channel_id


class _Channel:
    def __init__(self, name: str) -> None:
        self.name = name


class _Session:
    """Sesion falsa: devuelve el canal que se le ha dicho, o nada."""

    def __init__(self, channel: _Channel | None) -> None:
        self._channel = channel

    def get(self, _model: Any, _pk: Any) -> _Channel | None:
        return self._channel


def test_sin_destino_la_carpeta_es_el_video() -> None:
    """El comportamiento de siempre: un proyecto suelto se agrupa por su titulo."""
    project = _Project("Kai Cenat reacciona a Speed", None)

    assert _export_folder_name(_Session(None), project) == "Kai Cenat reacciona a Speed"  # type: ignore[arg-type]


def test_con_destino_la_carpeta_es_el_canal() -> None:
    """Lo que hace util la seccion de canales: todo lo de Speed en una carpeta."""
    project = _Project("Kai Cenat reacciona a Speed", CHANNEL)

    folder = _export_folder_name(_Session(_Channel("Speed Clips")), project)  # type: ignore[arg-type]

    assert folder == "Speed Clips"


def test_un_destino_que_ya_no_existe_no_deja_al_clip_sin_carpeta() -> None:
    """Borrar el canal de destino no puede perder los clips que iban a el.

    La clave ajena los deja en NULL, pero entre que se borra y se recarga el
    proyecto puede haber un id que ya no apunta a nada. Antes que fallar, se
    cae al titulo del video, que siempre existe.
    """
    project = _Project("Speed pierde en FIFA", uuid4())

    assert _export_folder_name(_Session(None), project) == "Speed pierde en FIFA"  # type: ignore[arg-type]
