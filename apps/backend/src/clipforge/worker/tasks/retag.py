"""Volver a etiquetar un proyecto sin re-renderizar nada.

Las etiquetas —quien sale, de que va, que clase de momento es— son lo unico
que permite repartir un clip entre varios canales. Los proyectos anteriores al
etiquetador no las tienen, y sin ellas sus clips no encajan en ningun canal por
mucho que los filtros esten bien puestos.

Rehacerlos enteros para conseguirlas seria pagar descarga, Whisper, analisis y
ffmpeg por un dato que sale de leer el titulo y la transcripcion. Esta tarea
hace solo esa lectura: minutos en vez de horas, y el MP4 no se toca.

Va a la cola ligera, como retitular: usa el modelo, pero ni transcribe ni
codifica, asi que no tiene por que esperar detras de un pipeline entero.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.db.models import ClipCandidate, ContentProfile, Project, Transcript
from clipforge.db.session import sync_session_scope
from clipforge.services.ai import AnalysisContext, ClipSuggestion, parse_keywords
from clipforge.services.ai.tagging import tag_clips
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="clipforge.tags.retag_project", bind=True)
def retag_project(self: Any, project_id: str) -> dict[str, Any]:
    """Pone etiquetas a los candidatos de un proyecto que no las tengan.

    A diferencia de retitular, aqui SI entran los candidatos manuales: quien
    corta un clip a mano decide donde empieza y como se llama, no a que canal
    pertenece, y dejarlos fuera los condenaria a no repartirse nunca.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    context, clips, ids = _load(pid)
    if not clips:
        log.info("retag.nothing_to_do")
        return {"project_id": project_id, "tagged": 0}

    tagged = tag_clips(clips, context)
    saved = _save(ids, tagged)

    log.info("retag.finished", clips=len(clips), tagged=saved)
    return {"project_id": project_id, "tagged": saved}


def _load(
    project_id: uuid.UUID,
) -> tuple[AnalysisContext, list[ClipSuggestion], list[uuid.UUID]]:
    """Reconstruye contexto y clips de lo que hay guardado.

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
                .order_by(ClipCandidate.rank, ClipCandidate.score.desc())
            ).scalars()
        )

        language = session.scalar(
            select(Transcript.language).where(Transcript.project_id == project_id).limit(1)
        )

        context = AnalysisContext(
            title=project.title,
            author=project.author,
            language=language,
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


def _save(ids: list[uuid.UUID], tagged: list[Any]) -> int:
    """Guarda las etiquetas que hayan salido y devuelve cuantas.

    Una etiqueta vacia NO se escribe encima de una que ya habia. El modelo
    puede quedarse callado sobre un clip, y tomarse ese silencio por "este
    clip no va de nada" borraria un dato bueno por una respuesta floja.
    """
    saved = 0

    with sync_session_scope() as session:
        for candidate_id, tag in zip(ids, tagged, strict=True):
            if tag.is_empty:
                continue

            candidate = session.get(ClipCandidate, candidate_id)
            if candidate is None:
                # Lo han borrado mientras se etiquetaba: ya no interesa.
                continue

            candidate.tags = tag.as_dict()
            saved += 1

    return saved
