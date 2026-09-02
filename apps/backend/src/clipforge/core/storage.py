"""Layout de almacenamiento local por proyecto.

Toda escritura a disco pasa por aqui para que la migracion futura a S3/R2 tenga
un unico punto de cambio, y para centralizar la defensa contra path traversal.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from clipforge.core.config import settings

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM_LENGTH = 80


class StorageArea(StrEnum):
    """Subcarpetas de `storage/projects/{project_id}/`."""

    SOURCE = "source"
    AUDIO = "audio"
    TRANSCRIPTS = "transcripts"
    CLIPS = "clips"
    SUBTITLES = "subtitles"
    TEMP = "temp"


def sanitize_filename(name: str, *, fallback: str = "file") -> str:
    """Convierte texto arbitrario (titulos de YouTube) en un nombre de fichero seguro."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # Descartamos cualquier componente de ruta tratando "/" y "\\" como separadores
    # en las dos plataformas: el worker puede correr en Linux y la API en Windows.
    stem = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_CHARS.sub("-", stem).strip("-._")
    cleaned = cleaned[:_MAX_STEM_LENGTH].strip("-._")
    return cleaned or fallback


class ProjectStorage:
    """Acceso a los ficheros de un proyecto concreto."""

    def __init__(self, project_id: UUID, *, root: Path | None = None) -> None:
        self.project_id = project_id
        self.base_root = (root or settings.storage_path).resolve()
        self.root = self.base_root / "projects" / str(project_id)

    # ------------------------------------------------------------------ rutas
    def area(self, area: StorageArea) -> Path:
        """Devuelve (creandolo) el directorio de un area."""
        path = self.root / area.value
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, area: StorageArea, filename: str) -> Path:
        """Ruta absoluta y validada para un fichero dentro de un area."""
        candidate = (self.area(area) / sanitize_filename(filename)).resolve()
        self.assert_within_root(candidate)
        return candidate

    def assert_within_root(self, path: Path) -> None:
        """Bloquea cualquier ruta que escape del storage del proyecto."""
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(f"Ruta fuera del storage del proyecto: {resolved}")

    # --------------------------------------------------------------- limpieza
    def ensure_layout(self) -> Path:
        """Crea el arbol completo de carpetas del proyecto."""
        for area in StorageArea:
            self.area(area)
        return self.root

    def cleanup(self, *, keep_source: bool | None = None, keep_audio: bool | None = None) -> None:
        """Borra los intermedios segun politica. Los clips finales nunca se tocan."""
        keep_source = settings.keep_source_video if keep_source is None else keep_source
        keep_audio = settings.keep_audio if keep_audio is None else keep_audio

        removable = [StorageArea.TEMP]
        if not keep_source:
            removable.append(StorageArea.SOURCE)
        if not keep_audio:
            removable.append(StorageArea.AUDIO)

        for area in removable:
            shutil.rmtree(self.root / area.value, ignore_errors=True)

    def delete_all(self) -> None:
        """Elimina por completo el storage del proyecto."""
        shutil.rmtree(self.root, ignore_errors=True)


def relative_to_storage(path: Path | str) -> str:
    """Guarda rutas relativas en BD para que el storage sea reubicable."""
    resolved = Path(path).resolve()
    root = settings.storage_path.resolve()
    if resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    return resolved.as_posix()


def absolute_from_storage(relative_path: str) -> Path:
    """Inversa de `relative_to_storage`, con validacion anti path traversal."""
    root = settings.storage_path.resolve()
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Ruta fuera del storage: {relative_path}")
    return resolved
