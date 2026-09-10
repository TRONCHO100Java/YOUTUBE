"""Reescribir los títulos de un proyecto sin volver a tocar el vídeo.

El título no está dentro del MP4. Cambiarlo es cambiar una fila y renombrar un
enlace en la carpeta de exportación, así que exigir un reprocesado completo
—descarga, Whisper, análisis, ffmpeg— para probar otro título era cobrar horas
de GPU por un trabajo de segundos.

Esta tarea hace justo eso y nada más: vuelve a llamar al redactor sobre los
candidatos que ya existen y guarda lo que devuelve. No re-renderiza, y por eso
**no toca el gancho**: ese sí va incrustado en los píxeles, y cambiarlo aquí
dejaría la base de datos diciendo una cosa y el vídeo enseñando otra.

Va a la cola ligera (`clipforge.titles.*` no encaja con la ruta de `pipeline.*`)
porque no necesita la tarjeta gráfica: cuando haya un segundo worker, retitular
no tendrá que esperar detrás de una transcripción.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.db.models import (
    CandidateSource,
    ClipCandidate,
    ContentProfile,
    Project,
)
from clipforge.db.session import sync_session_scope
from clipforge.services.ai import AnalysisContext, ClipSuggestion, parse_keywords, write_titles
from clipforge.worker.celery_app import celery_app
from clipforge.worker.tasks.pipeline import export_project_clips

logger = get_logger(__name__)


@celery_app.task(name="clipforge.titles.retitle_project", bind=True)
def retitle_project(self: Any, project_id: str) -> dict[str, Any]:
    """Reescribe los títulos de los candidatos generados de un proyecto.

    Los candidatos manuales quedan fuera: su título lo ha escrito una persona,
    y sustituirlo por el de un modelo porque alguien pulsó un botón de la
    pantalla de al lado sería justo lo contrario de lo que espera.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    context, clips, ids = _load(pid)
    if not clips:
        log.info("retitle.nothing_to_do")
        return {"project_id": project_id, "retitled": 0}

    titled = write_titles(clips, context)
    changed = _save(ids, clips, titled)

    # La carpeta de exportación nombra los ficheros por su título: si no se
    # regenera, el disco sigue enseñando los títulos viejos.
    if changed:
        export_project_clips(pid, log)

    log.info("retitle.finished", clips=len(clips), changed=changed)
    return {"project_id": project_id, "retitled": changed}


def _load(
    project_id: uuid.UUID,
) -> tuple[AnalysisContext, list[ClipSuggestion], list[uuid.UUID]]:
    """Reconstruye el contexto y los clips a partir de lo que hay guardado.

    Raises:
        ClipForgeError: si el proyecto ya no existe.
    """
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ClipForgeError(f"El proyecto {project_id} ya no existe")

        rows = list(
            session.execute(
                select(ClipCandidate)
                .where(ClipCandidate.project_id == project_id)
                .where(ClipCandidate.source != CandidateSource.MANUAL)
                .order_by(ClipCandidate.rank, ClipCandidate.score.desc())
            ).scalars()
        )

        context = AnalysisContext(
            title=project.title,
            author=project.author,
            profile=project.content_profile or ContentProfile.TALKING,
            duration=project.duration,
            keywords=parse_keywords(project.keywords),
        )
        clips = [
            ClipSuggestion(
                start_segment=row.start_segment_index,
                end_segment=row.end_segment_index,
                start_time=row.start_time,
                end_time=row.end_time,
                title=row.title,
                hook=row.hook,
                reason=row.reason,
                scores=None,
                transcript_excerpt=row.transcript_excerpt,
                source=row.source,
                signal_score=row.score,
            )
            for row in rows
        ]
        return context, clips, [row.id for row in rows]


def _save(ids: list[uuid.UUID], before: list[ClipSuggestion], after: list[ClipSuggestion]) -> int:
    """Guarda los títulos nuevos y devuelve cuántos han cambiado de verdad."""
    changed = 0

    with sync_session_scope() as session:
        for candidate_id, old, new in zip(ids, before, after, strict=True):
            candidate = session.get(ClipCandidate, candidate_id)
            if candidate is None:
                # Lo han borrado mientras se titulaba. No es un error: es que
                # ya no interesa.
                continue

            candidate.title = new.title
            candidate.title_variants = list(new.title_variants) or None
            candidate.description = new.description
            candidate.hashtags = list(new.hashtags) or None
            if old.title != new.title:
                changed += 1

    return changed
