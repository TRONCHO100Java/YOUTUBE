"""Carpeta de clips listos para subir, con nombres legibles.

El almacenamiento interno usa nombres opacos a proposito (`clip_01_9cd4a39e.mp4`
dentro de una carpeta con el UUID del proyecto): son estables, no dependen de lo
que devuelva un LLM y no colisionan. Pero nadie quiere subir eso a TikTok sin
saber cual es cual.

Esta capa deja una segunda vista de los mismos ficheros, ordenada por ranking y
nombrada con el titulo del clip. Es una vista derivada: se puede borrar entera
sin perder nada, y regenerarla es idempotente.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from clipforge.core.config import settings
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

#: Marca que dice de que proyecto es la carpeta. Sin ella, dos videos con el
#: mismo titulo mezclarian sus clips en silencio.
MARKER_NAME = ".clipforge-project"

#: Indice de la carpeta, con los datos de todos los clips en una tabla.
INDEX_NAME = "youtube.csv"

#: Salto de linea explicito: estos ficheros se escriben en Windows pero se
#: leen en cualquier sitio, y un CRLF dentro de un campo CSV rompe mas de un
#: lector.
NEWLINE = "\n"

#: Prohibidos en Windows (NTFS). En POSIX solo "/" lo esta, pero un nombre que
#: solo funcione en un sistema no sirve: estos ficheros se copian y se mueven.
_FORBIDDEN_CHARS = '<>:"/|?*\\'
#: Se borran junto con los caracteres de control, que tampoco sirven de nombre.
#: `translate` en vez de una expresion regular: una clase de caracteres con
#: barras invertidas dentro es justo donde se cuelan los errores de escapado.
_DELETIONS: dict[int, None] = {ord(char): None for char in _FORBIDDEN_CHARS} | dict.fromkeys(
    range(0x20)
)
#: `:` separa dos ideas, asi que se conserva como guion en lugar de borrarse.
_COLON = re.compile(r"\s*:\s*")
_WHITESPACE = re.compile(r"\s+")
#: Nombres de dispositivo heredados de MS-DOS: un fichero llamado "CON.mp4" no
#: se puede crear en Windows por mucho que el nombre parezca inofensivo.
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}
_MAX_LENGTH = 90


def export_filename(text: str, *, fallback: str = "clip") -> str:
    """Convierte un titulo en un nombre de fichero legible y seguro.

    A diferencia de `core.storage.sanitize_filename`, que reduce a ASCII porque
    su salida es una ruta interna, aqui se conservan tildes y espacios: el punto
    de esta carpeta es que se lea.

    Nunca devuelve un separador de ruta, ni `.`/`..`, ni cadena vacia, asi que
    el resultado no puede escaparse del directorio de destino.
    """
    # NFC agrupa los acentos en un solo punto de codigo. Sin esto macOS y
    # Windows escriben la misma "ñ" de dos formas distintas.
    normalized = unicodedata.normalize("NFC", text)
    cleaned = _COLON.sub(" - ", normalized).translate(_DELETIONS)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    cleaned = cleaned[:_MAX_LENGTH]
    # Windows recorta en silencio los puntos y espacios finales: si no se
    # quitan aqui, la ruta que se crea no es la que se pidio.
    cleaned = cleaned.rstrip(". ").strip()

    if not cleaned or cleaned.upper().split(".")[0] in _RESERVED:
        return fallback
    return cleaned


@dataclass(frozen=True, slots=True)
class ClipExport:
    """Un clip renderizado, con lo que hace falta para nombrarlo y subirlo."""

    rank: int
    title: str
    video: Path
    subtitles: Path | None = None
    description: str | None = None
    hashtags: tuple[str, ...] = ()
    start: float = 0.0
    end: float = 0.0


@dataclass(frozen=True, slots=True)
class SourceCredit:
    """De donde salio el video, para acreditarlo en la descripcion.

    Lo compone el sistema y no el modelo por dos razones: el modelo no
    conoce la URL, y el credito es justo lo que separa un clip de un
    reupload a ojos de YouTube. No es decoracion.
    """

    title: str | None = None
    author: str | None = None
    url: str | None = None

    def lines(self) -> list[str]:
        """Las lineas de credito, o ninguna si no se sabe de donde viene."""
        if not (self.title or self.author or self.url):
            return []

        source = " - ".join(part for part in (self.title, self.author) if part)
        lines = [f"Del video original: {source}" if source else "Video original:"]
        if self.url:
            lines.append(self.url)
        return lines


def export_root() -> Path:
    """Raiz de la carpeta de exportacion, configurable via `EXPORT_PATH`."""
    return settings.export_dir.resolve()


def export_project(
    project_id: UUID,
    project_title: str | None,
    clips: list[ClipExport],
    credit: SourceCredit | None = None,
) -> Path | None:
    """Deja los clips del proyecto en `export/{titulo}/` con nombres legibles.

    Devuelve la carpeta creada, o None si no habia nada que exportar.

    Se vuelve a construir entera en cada llamada: si un reproceso genera clips
    distintos, los antiguos no deben quedarse ahi haciendose pasar por buenos.
    """
    if not clips:
        return None

    folder = _project_folder(project_id, project_title)
    _clear(folder)
    folder.mkdir(parents=True, exist_ok=True)
    folder.joinpath(MARKER_NAME).write_text(str(project_id), encoding="utf-8")

    exported = 0
    for clip in sorted(clips, key=lambda item: item.rank):
        if not clip.video.is_file():
            logger.warning("export.clip_missing", rank=clip.rank, path=str(clip.video))
            continue
        stem = f"{clip.rank:02d} - {export_filename(clip.title, fallback=f'clip {clip.rank}')}"
        _link_or_copy(clip.video, folder / f"{stem}{clip.video.suffix}")
        if clip.subtitles is not None and clip.subtitles.is_file():
            _link_or_copy(clip.subtitles, folder / f"{stem}{clip.subtitles.suffix}")
        # El .txt al lado del .mp4: al subir se abre uno y se copia del otro,
        # sin volver a la aplicacion a buscar que decia este clip.
        folder.joinpath(f"{stem}.txt").write_text(
            clip_notes(clip, credit or SourceCredit()), encoding="utf-8"
        )
        exported += 1

    if exported:
        folder.joinpath(INDEX_NAME).write_text(
            clips_index(clips, credit or SourceCredit()), encoding="utf-8"
        )

    logger.info("export.finished", folder=str(folder), clips=exported)
    return folder


def clip_notes(clip: ClipExport, credit: SourceCredit) -> str:
    """El texto que se copia al subir el clip: titulo, descripcion, etiquetas.

    En bloques separados por lineas en blanco, en el mismo orden en que los
    pide el formulario de YouTube, para poder ir copiando de arriba abajo.
    """
    hashtags = " ".join(f"#{tag}" for tag in clip.hashtags)
    description = [clip.description] if clip.description else []
    body = [*description, *credit.lines()]

    blocks = [clip.title]
    if body:
        blocks.append(NEWLINE.join(body))
    if hashtags:
        blocks.append(hashtags)
    blocks.append(f"Del original {_clock(clip.start)} - {_clock(clip.end)}")

    return (NEWLINE * 2).join(blocks) + NEWLINE


def clips_index(clips: list[ClipExport], credit: SourceCredit) -> str:
    """Todos los clips de la carpeta en un CSV, para subirlos en tanda.

    La descripcion viaja con su credito ya incorporado: el CSV se abre en
    otro programa, y una descripcion a medias obligaria a volver aqui.
    """
    rows = [("orden", "titulo", "descripcion", "etiquetas", "fichero", "desde", "hasta")]
    for clip in sorted(clips, key=lambda item: item.rank):
        description = NEWLINE.join(
            [*([clip.description] if clip.description else []), *credit.lines()]
        )
        rows.append(
            (
                str(clip.rank),
                clip.title,
                description,
                " ".join(f"#{tag}" for tag in clip.hashtags),
                f"{clip.rank:02d} - {export_filename(clip.title)}{clip.video.suffix}",
                _clock(clip.start),
                _clock(clip.end),
            )
        )

    buffer = io.StringIO()
    # Excel en espanol espera el punto y coma; con coma mete todo en una
    # columna y el CSV deja de servir para lo unico que sirve.
    csv.writer(buffer, delimiter=";", lineterminator=NEWLINE).writerows(rows)
    return buffer.getvalue()


def _clock(seconds: float) -> str:
    """m:ss, que es como se leen los tiempos en el reproductor."""
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


def _project_folder(project_id: UUID, project_title: str | None) -> Path:
    """Carpeta del proyecto, desambiguada si otro ya ocupa ese titulo."""
    name = export_filename(project_title or "", fallback=f"proyecto {str(project_id)[:8]}")
    candidate = export_root() / name

    marker = candidate / MARKER_NAME
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() != str(project_id):
        # Dos videos distintos con el mismo titulo: el segundo lleva sufijo en
        # vez de sobrescribir los clips del primero.
        candidate = export_root() / f"{name} ({str(project_id)[:8]})"

    resolved = candidate.resolve()
    if not resolved.is_relative_to(export_root()):
        raise ValueError(f"Ruta de exportacion fuera de la raiz: {resolved}")
    return resolved


def _clear(folder: Path) -> None:
    """Vacia la carpeta si es nuestra; si tiene otra cosa dentro, no se toca."""
    if not folder.is_dir():
        return
    if not folder.joinpath(MARKER_NAME).is_file():
        logger.warning("export.folder_not_ours", folder=str(folder))
        return
    shutil.rmtree(folder, ignore_errors=True)


def _link_or_copy(source: Path, destination: Path) -> None:
    """Enlace duro si el sistema de ficheros deja; copia si no.

    Un enlace duro es otro nombre para los mismos bytes: exportar 15 clips no
    cuesta otro giga de disco. Cruzar volumenes o un sistema sin enlaces (FAT,
    algunos recursos de red) lanza OSError, y ahi si toca copiar.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
