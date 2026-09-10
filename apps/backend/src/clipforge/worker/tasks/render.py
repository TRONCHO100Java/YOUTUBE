"""Render de un único candidato, bajo demanda.

Es lo que hace posible el editor manual: el usuario marca entrada y salida
sobre la línea de tiempo, pulsa renderizar y solo se recodifican esos segundos.
Sin esto, la única forma de obtener un MP4 era volver a pasar el vídeo entero
por descarga, transcripción y análisis.

Comparte con el pipeline exactamente el mismo código de render
(`render_and_store`): un clip manual y uno propuesto por la IA son el mismo
fichero con el mismo encuadre, y tener dos caminos que producen "casi" lo mismo
es la forma más segura de que uno de los dos se quede atrás.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from clipforge.core.errors import ClipForgeError, NotFoundError
from clipforge.core.logging import get_logger
from clipforge.core.storage import absolute_from_storage
from clipforge.db.models import (
    CandidateStatus,
    ClipCandidate,
    ContentProfile,
    Project,
)
from clipforge.db.session import sync_session_scope
from clipforge.services.ai import rules_for
from clipforge.services.render_clip import ClipRenderPlan, build_setup
from clipforge.worker.celery_app import celery_app
from clipforge.worker.tasks.pipeline import (
    clip_peaks,
    export_project_clips,
    render_and_store,
    subtitle_segments,
    transcript_words,
    update_candidate,
)

logger = get_logger(__name__)


@celery_app.task(name="clipforge.pipeline.render_candidate", bind=True)
def render_candidate(self: Any, candidate_id: str) -> dict[str, Any]:
    """Genera el clip de un candidato concreto.

    Va a la cola `gpu` como el pipeline (por el prefijo `clipforge.pipeline.`):
    compite por la misma tarjeta, así que dejarlo en la cola ligera solo serviría
    para que dos ffmpeg se peleen por el codificador.
    """
    cid = uuid.UUID(candidate_id)
    log = logger.bind(candidate_id=candidate_id, task_id=self.request.id)

    try:
        plan, setup, project_id = _prepare(cid)
        render_and_store(plan, setup)
        # La carpeta de exportacion es donde el usuario coge los ficheros para
        # subirlos. Sin esto, un clip recortado a mano se generaba pero no
        # aparecia donde se buscan los demas.
        export_project_clips(project_id, log)
    except ClipForgeError as exc:
        log.warning("render.candidate_failed", code=exc.code, error=exc.message)
        update_candidate(cid, status=CandidateStatus.FAILED, error_message=exc.message)
        return {
            "candidate_id": candidate_id,
            "status": CandidateStatus.FAILED,
            "error": exc.message,
        }
    except Exception as exc:
        log.error("render.candidate_crashed", exc_info=exc)
        update_candidate(
            cid, status=CandidateStatus.FAILED, error_message=f"Error inesperado: {exc}"
        )
        raise

    log.info("render.candidate_done", rank=plan.rank)
    return {"candidate_id": candidate_id, "status": CandidateStatus.RENDERED}


def _prepare(candidate_id: uuid.UUID) -> tuple[ClipRenderPlan, Any, uuid.UUID]:
    """Reúne el plan y el encuadre en una transacción corta.

    Raises:
        NotFoundError: si el candidato o su vídeo de origen ya no existen.
    """
    with sync_session_scope() as session:
        candidate = session.get(ClipCandidate, candidate_id)
        if candidate is None:
            raise NotFoundError(f"El candidato {candidate_id} ya no existe")

        project = session.get(Project, candidate.project_id)
        if project is None or not project.source_video_path:
            raise NotFoundError(
                "El vídeo original ya no está disponible. Vuelve a procesar el "
                "proyecto para descargarlo otra vez."
            )

        plan = ClipRenderPlan(
            candidate_id=candidate.id,
            rank=candidate.rank or 1,
            start=candidate.start_time,
            end=candidate.end_time,
            hook=candidate.hook,
            crop_x=candidate.crop_x,
            story=candidate.story,
        )
        project_id = project.id
        video_relative = project.source_video_path
        rules = rules_for(project.content_profile or ContentProfile.TALKING)
        burn = rules.burn_subtitles
        segments = subtitle_segments(session, project_id)
        words = transcript_words(session, project_id)
        peaks = clip_peaks(project.signals)

    source = absolute_from_storage(video_relative)
    if not source.is_file():
        raise NotFoundError(
            "El vídeo original ya no está en disco. Vuelve a procesar el "
            "proyecto para descargarlo otra vez."
        )

    setup = build_setup(
        project_id,
        source,
        segments,
        burn_subtitles=burn,
        sample_at=plan.start,
        words=words,
        trim_silences=rules.trim_silences,
        peaks=peaks,
    )
    return plan, setup, project_id


def pending_candidate_ids(project_id: uuid.UUID) -> list[uuid.UUID]:
    """Candidatos del proyecto que aún no tienen clip generado."""
    with sync_session_scope() as session:
        return list(
            session.execute(
                select(ClipCandidate.id)
                .where(ClipCandidate.project_id == project_id)
                .where(
                    ClipCandidate.status.in_(
                        [CandidateStatus.PENDING, CandidateStatus.SELECTED, CandidateStatus.FAILED]
                    )
                )
                .order_by(ClipCandidate.rank)
            ).scalars()
        )
