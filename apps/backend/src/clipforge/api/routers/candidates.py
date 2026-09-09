"""Endpoints de candidatos: crear, ajustar, descartar y renderizar a mano.

Es la mitad del editor manual que vive en el backend. La otra mitad —saber
dónde mirar— la aporta la línea de tiempo de señales, que se sirve desde el
router de proyectos.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from clipforge.api.deps import CandidateRepo
from clipforge.api.schemas.candidate import ClipCandidateRead, ClipCandidateUpdate
from clipforge.core.errors import ConflictError, NotFoundError, ValidationError
from clipforge.core.logging import get_logger
from clipforge.db.models import CandidateStatus, ClipCandidate

router = APIRouter(prefix="/candidates", tags=["candidates"])
logger = get_logger(__name__)

#: Estados desde los que NO tiene sentido lanzar un render.
BUSY_STATUSES = frozenset({CandidateStatus.RENDERING})


@router.get("/{candidate_id}", response_model=ClipCandidateRead, summary="Detalle de un candidato")
async def get_candidate(candidate_id: uuid.UUID, repo: CandidateRepo) -> ClipCandidateRead:
    return ClipCandidateRead.from_model(await _require(candidate_id, repo))


@router.patch(
    "/{candidate_id}",
    response_model=ClipCandidateRead,
    summary="Ajustar entrada, salida o título",
)
async def update_candidate(
    candidate_id: uuid.UUID, payload: ClipCandidateUpdate, repo: CandidateRepo
) -> ClipCandidateRead:
    """Ajusta un candidato sin volver a renderizarlo.

    El clip que ya hubiera generado se conserva a propósito: el usuario suele
    ajustar y comparar antes de decidir, y borrarle el vídeo anterior en cada
    arrastre lo dejaría sin nada que mirar mientras tanto.
    """
    candidate = await _require(candidate_id, repo)

    start = payload.start_time if payload.start_time is not None else candidate.start_time
    end = payload.end_time if payload.end_time is not None else candidate.end_time
    if end <= start:
        raise ValidationError(
            f"La salida ({end:.1f}s) tiene que ir por detrás de la entrada ({start:.1f}s)"
        )
    _assert_within_source(candidate, start, end)

    candidate.start_time = start
    candidate.end_time = end
    if payload.title is not None:
        candidate.title = payload.title.strip()
    if payload.crop_x is not None:
        # -1 es "vuelve a decidirlo tú": deja la columna en NULL y el próximo
        # render recalcula el encuadre automático.
        candidate.crop_x = None if payload.crop_x < 0 else payload.crop_x
    if payload.hook is not None:
        # Cadena vacía = quitar el gancho. Guardar "" en lugar de NULL haría
        # que el render escribiese una línea en blanco sobre el vídeo.
        candidate.hook = payload.hook.strip() or None
    if payload.status is not None:
        candidate.status = payload.status
    # Los índices de segmento describían el rango anterior: al mover las marcas
    # dejan de ser ciertos, y un dato desactualizado engaña más que uno ausente.
    if payload.start_time is not None or payload.end_time is not None:
        candidate.start_segment_index = None
        candidate.end_segment_index = None

    await repo.session.commit()
    logger.info("candidate.updated", candidate_id=str(candidate_id))
    # Se relee por el repositorio: `refresh` expira la relación con el clip y
    # volver a tocarla sería una carga perezosa dentro del contexto asíncrono.
    return ClipCandidateRead.from_model(await _require(candidate_id, repo))


@router.delete(
    "/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar un candidato"
)
async def delete_candidate(candidate_id: uuid.UUID, repo: CandidateRepo) -> None:
    """Borra el candidato y, en cascada, el clip que hubiera generado."""
    candidate = await _require(candidate_id, repo)
    await repo.delete(candidate)
    await repo.session.commit()
    logger.info("candidate.deleted", candidate_id=str(candidate_id))


@router.post(
    "/{candidate_id}/render",
    response_model=ClipCandidateRead,
    summary="Renderizar este candidato",
)
async def render_candidate_endpoint(
    candidate_id: uuid.UUID, repo: CandidateRepo
) -> ClipCandidateRead:
    """Encola el render de un único clip.

    Raises:
        ConflictError: si ese candidato ya se está renderizando.
    """
    candidate = await _require(candidate_id, repo)
    if candidate.status in BUSY_STATUSES:
        raise ConflictError("Ese clip ya se está generando; espera a que termine")

    candidate.status = CandidateStatus.SELECTED
    candidate.error_message = None
    # Commit ANTES de encolar: si el worker recogiera la tarea antes de que el
    # cambio estuviera visible, renderizaría con los tiempos antiguos.
    await repo.session.commit()

    _enqueue(candidate_id)
    logger.info("candidate.render_queued", candidate_id=str(candidate_id))
    return ClipCandidateRead.from_model(await _require(candidate_id, repo))


async def _require(candidate_id: uuid.UUID, repo: CandidateRepo) -> ClipCandidate:
    candidate = await repo.get(candidate_id)
    if candidate is None:
        raise NotFoundError(f"Candidato {candidate_id} no encontrado")
    return candidate


def _assert_within_source(candidate: ClipCandidate, start: float, end: float) -> None:
    """Comprueba que el rango cabe en el vídeo original.

    Se valida contra la duración que guardó ffprobe, no contra la anunciada por
    YouTube: pedirle a ffmpeg un tramo que no existe produce un fichero vacío y
    un error mucho más difícil de leer que este.
    """
    duration = candidate.project.duration if candidate.project else None
    if duration and end > duration + 1.0:
        raise ValidationError(f"La salida ({end:.1f}s) se sale del vídeo, que dura {duration:.1f}s")
    if start < 0:
        raise ValidationError("La entrada no puede ser negativa")


def _enqueue(candidate_id: uuid.UUID) -> str:
    """Encola el render y devuelve el id de la tarea Celery."""
    from clipforge.worker.tasks.render import render_candidate

    return str(render_candidate.delay(str(candidate_id)).id)
