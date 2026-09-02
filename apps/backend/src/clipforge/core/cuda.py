"""Preparación del runtime CUDA en Windows.

ctranslate2 (el motor de faster-whisper) carga cuBLAS y cuDNN por nombre usando
el orden de búsqueda de DLL por defecto de Windows, que consulta el PATH pero
NO los directorios registrados con `os.add_dll_directory`. Como esas librerías
se instalan vía pip dentro de `site-packages/nvidia/*/bin`, hay que añadirlas al
PATH del proceso antes de cargar el primer modelo o falla con:

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

En Linux no hace falta: los paquetes de NVIDIA se resuelven por RPATH.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

from clipforge.core.logging import get_logger

logger = get_logger(__name__)

_prepared = False


def ensure_cuda_libraries() -> list[Path]:
    """Hace visibles las librerías CUDA instaladas por pip. Idempotente."""
    global _prepared
    if _prepared or sys.platform != "win32":
        return []

    nvidia_root = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    bin_dirs = sorted(nvidia_root.glob("*/bin")) if nvidia_root.is_dir() else []

    if not bin_dirs:
        logger.warning("cuda.libraries_not_found", searched=str(nvidia_root))
        _prepared = True
        return []

    current = os.environ.get("PATH", "")
    missing = [d for d in bin_dirs if str(d) not in current]
    if missing:
        os.environ["PATH"] = os.pathsep.join(str(d) for d in missing) + os.pathsep + current

    for directory in bin_dirs:
        # Redundante con el PATH, pero necesario para las extensiones de Python
        # que sí usan LOAD_LIBRARY_SEARCH_USER_DIRS.
        os.add_dll_directory(str(directory))

    logger.info("cuda.libraries_ready", packages=[d.parent.name for d in bin_dirs])
    _prepared = True
    return bin_dirs
