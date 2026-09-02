"""Resolucion de rutas del repositorio.

El backend se puede ejecutar desde cualquier directorio (uvicorn, celery, pytest,
alembic), por lo que nunca dependemos del cwd: subimos por el arbol hasta encontrar
el marcador del monorepo.
"""

from __future__ import annotations

from pathlib import Path

_ROOT_MARKERS = ("docker-compose.yml", ".git")


def find_repo_root(start: Path | None = None) -> Path:
    """Devuelve la raiz del monorepo buscando hacia arriba un marcador conocido."""
    origin = (start or Path(__file__).resolve()).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    # Fallback: src/clipforge/core/paths.py -> apps/backend/src/clipforge/core
    return Path(__file__).resolve().parents[5]


REPO_ROOT: Path = find_repo_root()
BACKEND_ROOT: Path = Path(__file__).resolve().parents[3]
