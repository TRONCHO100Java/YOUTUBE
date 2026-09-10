"""El juez: qué candidatos merecen convertirse en Shorts.

Hasta ahora detectar y elegir eran la misma cosa. El modelo que leía la
transcripción proponía momentos con su nota, y esa nota decidía. Tiene dos
problemas: el que propone juzga su propio trabajo —y nunca ve más de una ventana
de cinco minutos a la vez—, así que compara un momento contra nada.

Aquí se separan. El **detector** barre el vídeo entero y propone en bruto,
generoso: treinta candidatos en vez de cinco. El **juez** los ve todos juntos,
los puntúa con una rúbrica pensada para Shorts y se queda con los mejores. Es
UNA llamada por proyecto (o unas pocas, por tandas), así que es justo donde
compensa pagar un modelo bueno aunque el detector corra en local:
`AI_JUDGE_PROVIDER`.

La rúbrica no pregunta "¿es interesante?". Pregunta lo que decide que un Short
funcione: si engancha en el primer segundo, si tiene remate, si se entiende sin
haber visto el original, y **cuánto lastre lleva** — porque el tiempo muerto y
el contexto que hay que explicar no restan puntos por ser feos, restan
espectadores.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.client import ask_json, resolve_model
from clipforge.services.ai.prompts_judge import build_judge_system_prompt, build_judge_user_prompt

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Criterion:
    """Una dimensión de la rúbrica del juez."""

    key: str
    maximum: int
    description: str
    #: Los castigos restan. Se preguntan como "cuánto de esto hay", que un
    #: modelo responde mucho mejor que "cuánto te gusta esto".
    penalty: bool = False


#: Lo que suma. Los pesos dicen qué importa: el gancho y el remate valen más
#: que todo lo demás junto porque son los que deciden si el vídeo se ve entero.
MERITS: tuple[Criterion, ...] = (
    Criterion("hook", 18, "fuerza del primer segundo para frenar el dedo"),
    Criterion("payoff", 15, "hay un remate de verdad, no se queda a medias"),
    Criterion("curiosity", 12, "genera necesidad de saber cómo acaba"),
    Criterion("standalone", 12, "se entiende sin haber visto el vídeo original"),
    Criterion("humor", 10, "hace gracia de verdad"),
    Criterion("surprise", 8, "pasa algo que no se veía venir"),
    Criterion("emotion", 8, "carga emocional: tensión, ternura, indignación"),
    Criterion("controversy", 7, "invita a discutir o a tomar partido"),
    Criterion("person", 5, "sale alguien a quien la gente busca por su nombre"),
    Criterion("shareability", 3, "ganas de mandárselo a alguien"),
    Criterion("comments", 2, "deja algo sobre lo que opinar"),
)

#: Lo que resta. No son defectos estéticos: son espectadores que se van.
PENALTIES: tuple[Criterion, ...] = (
    Criterion(
        "context_needed",
        10,
        "cuánto hay que saber de antes para entenderlo; referencias a algo "
        "anterior que el espectador no ha visto",
        penalty=True,
    ),
    Criterion(
        "dead_time",
        10,
        "silencios, repeticiones, muletillas y relleno dentro del momento",
        penalty=True,
    ),
    Criterion(
        "weak_start",
        10,
        "tarda en llegar a lo interesante: saludos, presentaciones, frases empezadas a medias",
        penalty=True,
    ),
)

CRITERIA: tuple[Criterion, ...] = (*MERITS, *PENALTIES)

#: Suma de los méritos. Los castigos bajan desde ahí.
MAX_SCORE = sum(criterion.maximum for criterion in MERITS)

#: Por debajo de esto un candidato no merece un Short, aunque sea de los
#: mejores del vídeo. Es la diferencia entre publicar cinco cosas y publicar
#: cinco cosas buenas.
MIN_PUBLISHABLE = 45

#: "Pregúntale al juez y devuélveme el JSON". Se inyecta en los tests.
Ask = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class Verdict:
    """Lo que el juez dice de un candidato."""

    scores: dict[str, int]
    reason: str

    @property
    def merit(self) -> int:
        return sum(self.scores.get(c.key, 0) for c in MERITS)

    @property
    def penalty(self) -> int:
        return sum(self.scores.get(c.key, 0) for c in PENALTIES)

    @property
    def total(self) -> float:
        """Nota final, acotada a 0-100.

        La suma la hacemos aquí y no se la pedimos al modelo: los LLM se
        equivocan sumando, y un total incoherente con su propio desglose es
        imposible de depurar. Es la misma regla que en el análisis.
        """
        return float(max(0, min(100, self.merit - self.penalty)))


def judge_candidates(
    candidates: Sequence[ClipSuggestion],
    context: AnalysisContext,
    *,
    limit: int,
    ask: Ask | None = None,
) -> list[ClipSuggestion]:
    """Puntúa los candidatos y devuelve los mejores, de mejor a peor.

    Si el juez falla o no dice nada, se devuelve lo que había ordenado por su
    nota anterior: el detector ya los había puntuado, peor pero no a ciegas. Un
    fallo aquí no puede dejar un proyecto sin clips.
    """
    pool = list(candidates)
    if not pool or not settings.judge_enabled:
        return pool[:limit]

    started = time.perf_counter()
    request = ask or _ask_provider
    verdicts: dict[int, Verdict] = {}

    for batch_start in range(0, len(pool), max(1, settings.judge_batch_size)):
        batch = pool[batch_start : batch_start + max(1, settings.judge_batch_size)]
        try:
            verdicts.update(_judge_batch(batch, batch_start, context, request))
        except ExternalToolError as exc:
            # Una tanda fallida no invalida las demás: los candidatos que no
            # llegan a juzgarse conservan la nota del detector.
            logger.warning("ai.judge_batch_failed", offset=batch_start, error=exc.message)

    if not verdicts:
        logger.warning("ai.judge_empty", candidates=len(pool))
        return pool[:limit]

    judged = _apply(pool, verdicts)
    chosen = [clip for clip in judged if clip.score >= MIN_PUBLISHABLE][:limit]

    # Si la vara de medir deja el proyecto sin nada, se publica lo mejor que
    # haya: un clip mediocre es peor que uno bueno y mejor que ninguno, que es
    # lo que el pipeline lleva evitando desde la fase 6.
    if not chosen:
        logger.info("ai.judge_below_bar", best=judged[0].score if judged else 0)
        chosen = judged[:limit]

    logger.info(
        "ai.judged",
        candidates=len(pool),
        judged=len(verdicts),
        chosen=len(chosen),
        top=chosen[0].score if chosen else None,
        seconds=round(time.perf_counter() - started, 1),
    )
    return chosen


# ------------------------------------------------------------------ privado
def _judge_batch(
    batch: Sequence[ClipSuggestion],
    offset: int,
    context: AnalysisContext,
    ask: Ask,
) -> dict[int, Verdict]:
    """Juzga una tanda y devuelve los veredictos por índice global."""
    content = ask(
        build_judge_system_prompt(CRITERIA, minimum=MIN_PUBLISHABLE, maximum=MAX_SCORE),
        build_judge_user_prompt(batch, context, offset=offset),
    )
    return parse_verdicts(content, offset=offset, size=len(batch))


def parse_verdicts(content: str, *, offset: int, size: int) -> dict[int, Verdict]:
    """Lee la respuesta del juez y la valida.

    Raises:
        ExternalToolError: si no encaja con el esquema acordado.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]

    try:
        payload = _model(Any).model_validate_json(text)
    except ValidationError as exc:
        raise ExternalToolError(
            "El juez ha devuelto algo que no encaja con el esquema",
            details={"error": str(exc)[:400], "content": text[:400]},
        ) from exc

    verdicts: dict[int, Verdict] = {}
    for item in payload.clips:  # type: ignore[attr-defined]
        # El juez numera desde 1 dentro de su tanda; fuera, lo que importa es
        # la posición en la lista completa.
        position = offset + item.clip - 1
        if not offset <= position < offset + size:
            continue
        verdicts[position] = Verdict(
            scores={c.key: _clamp(getattr(item, c.key, 0), c.maximum) for c in CRITERIA},
            reason=str(getattr(item, "reason", "")).strip(),
        )

    return verdicts


def _apply(pool: Sequence[ClipSuggestion], verdicts: dict[int, Verdict]) -> list[ClipSuggestion]:
    """Sustituye la nota del detector por la del juez, y reordena."""
    judged: list[ClipSuggestion] = []

    for index, clip in enumerate(pool):
        verdict = verdicts.get(index)
        if verdict is None:
            judged.append(clip)
            continue
        judged.append(
            replace(
                clip,
                scores=None,
                signal_score=verdict.total,
                judge_scores=verdict.scores,
                reason=verdict.reason or clip.reason,
            )
        )

    return sorted(judged, key=lambda clip: (clip.score, -clip.start_time), reverse=True)


def _clamp(value: Any, maximum: int) -> int:
    """Acota lo que devuelve el modelo al rango de su dimensión."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, number))


def _model(annotation: Any) -> type[BaseModel]:
    """Construye el modelo de la respuesta desde la rúbrica.

    Se genera y no se escribe a mano por lo mismo que el prompt: si se toca
    un peso o se añade un criterio, los dos cambian juntos y no pueden
    quedar desincronizados.

    El tipo de los campos es un parámetro porque se necesitan dos versiones.
    Al proveedor se le exigen enteros —para eso está el esquema—, pero al
    LEER se acepta cualquier cosa: si un modelo devuelve "mucho" en una nota
    de catorce, perder por eso la tanda entera de diez candidatos sería
    tirar el trabajo bueno por culpa del malo. `_clamp` lo convierte en cero
    y sigue.
    """
    fields: dict[str, Any] = {
        criterion.key: (
            annotation,
            Field(description=f"{criterion.description}, 0-{criterion.maximum}"),
        )
        for criterion in CRITERIA
    }
    fields["clip"] = (int, Field(description="Número del clip que se te ha dado"))
    fields["reason"] = (str, Field(description="Una frase: por qué esa nota"))

    item = create_model("Judgement", __config__=ConfigDict(extra="ignore"), **fields)
    return create_model(
        "Judgements",
        __config__=ConfigDict(extra="ignore"),
        clips=(list[item], Field(description="Una entrada por clip")),
    )


def _schema() -> dict[str, Any]:
    """Lo que se le exige al proveedor: enteros, no lo que le apetezca."""
    schema = _model(int).model_json_schema()
    schema["additionalProperties"] = False
    return schema


def _ask_provider(system: str, user: str) -> str:
    """Le pide el veredicto al modelo configurado para juzgar."""
    return ask_json(
        system,
        user,
        schema=_schema(),
        choice=resolve_model(settings.ai_judge_provider, settings.ai_judge_model),
        # Determinista: juzgar dos veces el mismo vídeo debe dar el mismo top 5,
        # o comparar cambios en la rúbrica es imposible.
        temperature=0.0,
        timeout_multiplier=2,
    )
