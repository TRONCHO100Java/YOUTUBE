"""Esquema de respuesta compartido por todos los proveedores de IA.

Un único esquema para OpenAI, Anthropic y Ollama: cada uno lo envía con su
propio mecanismo de salida estructurada, pero el contrato es el mismo, así que
cambiar de proveedor no cambia lo que hay que parsear.

El esquema se **construye a partir del perfil de contenido**, porque las
dimensiones de la puntuación cambian con él: un pódcast se puntúa por
`value_score` y un gag visual por `payoff_score`. Generarlo evita mantener dos
modelos a mano y, sobre todo, evita que el modelo reciba un campo cuyo nombre
no encaja con lo que se le está pidiendo que valore.

Deliberadamente NO lleva restricciones numéricas (`ge`/`le`): los modos
estrictos de OpenAI y Anthropic no admiten `minimum`/`maximum`, y en cualquier
caso hay que acotar los valores del modelo por nuestra cuenta. El rango se
valida en `resolver.py`.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.profiles import ProfileRules


class RawCandidateBase(BaseModel):
    """Campos comunes a cualquier momento propuesto por un modelo."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="Título corto y atractivo, en español")
    hook: str = Field(description="La frase o imagen de apertura que engancha")
    reason: str = Field(description="Por qué este momento funcionaría como clip")

    def score_for(self, field_name: str) -> int:
        """Puntuación de una dimensión, o 0 si el modelo la ha omitido."""
        value = getattr(self, field_name, 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class RawClipCandidate(RawCandidateBase):
    """Momento propuesto sobre una ventana de transcripción."""

    start_segment: int = Field(description="Índice del primer segmento del clip")
    end_segment: int = Field(description="Índice del último segmento, incluido")


class RawVisionCandidate(RawCandidateBase):
    """Momento propuesto sobre un bloque de fotogramas.

    El modelo no elige tiempos: elige un bloque de los que se le han enseñado y,
    como mucho, dice cuántos segundos sobran por delante y por detrás. Es la
    misma regla que en el análisis de texto — el backend deriva los timestamps —
    aplicada a un vídeo que no se puede describir con índices de segmento.
    """

    block: int = Field(description="Índice del bloque que se te ha mostrado")
    trim_start: int = Field(description="Segundos de más al principio del bloque, 0 si ninguno")
    trim_end: int = Field(description="Segundos de más al final del bloque, 0 si ninguno")


@lru_cache(maxsize=8)
def candidate_model(rules: ProfileRules, *, vision: bool = False) -> type[RawCandidateBase]:
    """Modelo de un candidato con las dimensiones del perfil dado."""
    base = RawVisionCandidate if vision else RawClipCandidate
    fields: dict[str, Any] = {
        dimension.field_name: (
            int,
            Field(description=f"{dimension.description}, 0-{dimension.maximum}"),
        )
        for dimension in rules.dimensions
    }
    name = f"{'Vision' if vision else 'Clip'}Candidate{rules.profile.value.title()}"
    return create_model(name, __base__=base, **fields)


@lru_cache(maxsize=8)
def response_model(rules: ProfileRules, *, vision: bool = False) -> type[BaseModel]:
    """Respuesta completa de una ventana o de una tanda de bloques."""
    item = candidate_model(rules, vision=vision)
    return create_model(
        f"AnalysisResponse{rules.profile.value.title()}{'Vision' if vision else ''}",
        __config__=ConfigDict(extra="ignore"),
        candidates=(
            list[item],  # type: ignore[valid-type]
            Field(description=("Los mejores momentos encontrados; lista vacía si no hay ninguno")),
        ),
    )


def response_json_schema(rules: ProfileRules, *, vision: bool = False) -> dict[str, Any]:
    """Esquema JSON estricto, en el formato que aceptan los tres proveedores.

    Todas las propiedades son obligatorias y `additionalProperties` es `false`,
    que es lo que exigen los modos estrictos de OpenAI y Anthropic.
    """
    schema: dict[str, Any] = response_model(rules, vision=vision).model_json_schema()
    strict: dict[str, Any] = _make_strict(_inline_defs(schema))
    return strict


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Sustituye las `$ref` por su definición.

    Pydantic saca el modelo del elemento a `$defs` y lo referencia. Ollama y el
    modo estricto de Anthropic no siempre resuelven esas referencias, y el
    esquema es lo bastante pequeño como para que insertarlo salga gratis.
    """
    defs: dict[str, Any] = schema.pop("$defs", {})
    if not defs:
        return schema

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(defs.get(ref.rsplit("/", 1)[-1], {}))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def _make_strict(node: Any) -> Any:
    """Marca todo objeto como cerrado y todas sus propiedades como requeridas."""
    if isinstance(node, dict):
        result = {key: _make_strict(value) for key, value in node.items()}
        if result.get("type") == "object" and "properties" in result:
            result["additionalProperties"] = False
            result["required"] = list(result["properties"].keys())
        return result
    if isinstance(node, list):
        return [_make_strict(item) for item in node]
    return node


#: Algunos modelos locales envuelven el JSON en un bloque markdown pese a
#: pedirles salida estructurada.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_analysis(
    payload: str | dict[str, Any], rules: ProfileRules, *, vision: bool = False
) -> list[RawCandidateBase]:
    """Convierte la respuesta de un proveedor en candidatos sin validar.

    Acepta la forma canónica `{"candidates": [...]}` y también una lista suelta,
    que es lo que devuelven algunos modelos pequeños.

    Raises:
        ExternalToolError: si la respuesta no es JSON o no encaja con el esquema.
    """
    data = _to_object(payload)

    if isinstance(data, list):
        data = {"candidates": data}
    if not isinstance(data, dict):
        raise ExternalToolError(
            "La IA ha devuelto una estructura inesperada",
            details={"type": type(data).__name__},
        )

    try:
        parsed = response_model(rules, vision=vision).model_validate(data)
    except ValidationError as exc:
        raise ExternalToolError(
            "La respuesta de la IA no encaja con el esquema esperado",
            details={"errors": exc.errors()[:5]},
        ) from exc
    candidates: list[RawCandidateBase] = list(parsed.candidates)  # type: ignore[attr-defined]
    return candidates


def _to_object(payload: str | dict[str, Any]) -> Any:
    if isinstance(payload, dict):
        return payload

    text = payload.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExternalToolError(
            "La IA no ha devuelto JSON válido",
            details={"response": text[:500]},
        ) from exc
