"""Esquema de respuesta compartido por todos los proveedores de IA.

Un único esquema para OpenAI, Anthropic y Ollama: cada uno lo envía con su
propio mecanismo de salida estructurada, pero el contrato es el mismo, así que
cambiar de proveedor no cambia lo que hay que parsear.

Deliberadamente NO lleva restricciones numéricas (`ge`/`le`): los modos
estrictos de OpenAI y Anthropic no admiten `minimum`/`maximum`, y en cualquier
caso hay que acotar los valores del modelo por nuestra cuenta. El rango se
valida en `resolver.py`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipforge.core.errors import ExternalToolError


class RawClipCandidate(BaseModel):
    """Un momento propuesto, tal y como lo devuelve el modelo."""

    model_config = ConfigDict(extra="ignore")

    start_segment: int = Field(description="Índice del primer segmento del clip")
    end_segment: int = Field(description="Índice del último segmento, incluido")
    title: str = Field(description="Título corto y atractivo, en el idioma del vídeo")
    hook: str = Field(description="La frase de apertura que engancha, citada del texto")
    reason: str = Field(description="Por qué este momento funcionaría como clip")
    hook_score: int = Field(description="Fuerza del gancho inicial, 0-20")
    curiosity_score: int = Field(description="Curiosidad que genera, 0-20")
    emotion_score: int = Field(description="Carga emocional, 0-15")
    clarity_score: int = Field(description="Se entiende sin contexto previo, 0-15")
    value_score: int = Field(description="Valor práctico o informativo, 0-15")
    shareability_score: int = Field(description="Ganas de compartirlo o debatirlo, 0-10")
    duration_score: int = Field(description="Idoneidad de la duración, 0-5")


class RawAnalysisResponse(BaseModel):
    """Respuesta completa de una ventana."""

    model_config = ConfigDict(extra="ignore")

    candidates: list[RawClipCandidate] = Field(
        description="Los mejores momentos de este fragmento; lista vacía si no hay ninguno"
    )


def response_json_schema() -> dict[str, Any]:
    """Esquema JSON estricto, en el formato que aceptan los tres proveedores.

    Todas las propiedades son obligatorias y `additionalProperties` es `false`,
    que es lo que exigen los modos estrictos de OpenAI y Anthropic.
    """
    schema: dict[str, Any] = RawAnalysisResponse.model_json_schema()
    strict: dict[str, Any] = _make_strict(schema)
    return strict


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


def parse_analysis(payload: str | dict[str, Any]) -> list[RawClipCandidate]:
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
        return RawAnalysisResponse.model_validate(data).candidates
    except ValidationError as exc:
        raise ExternalToolError(
            "La respuesta de la IA no encaja con el esquema esperado",
            details={"errors": exc.errors()[:5]},
        ) from exc


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
