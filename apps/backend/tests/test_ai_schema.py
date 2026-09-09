"""Esquema compartido y parseo de la respuesta de los proveedores."""

from __future__ import annotations

import json

import pytest

from clipforge.core.errors import ExternalToolError
from clipforge.db.models.enums import ContentProfile
from clipforge.services.ai.profiles import rules_for
from clipforge.services.ai.schema import parse_analysis, response_json_schema

#: La rúbrica de contenido hablado, que es la que usan estos casos.
RULES = rules_for(ContentProfile.TALKING)

CANDIDATE = {
    "start_segment": 3,
    "end_segment": 7,
    "title": "Un título",
    "hook": "Un gancho",
    "reason": "Un motivo",
    "hook_score": 18,
    "curiosity_score": 17,
    "emotion_score": 12,
    "clarity_score": 11,
    "value_score": 10,
    "shareability_score": 6,
    "duration_score": 4,
}


def test_schema_is_strict_enough_for_openai_and_anthropic() -> None:
    """Ambos exigen additionalProperties=false y todas las claves en required."""
    schema = response_json_schema(RULES)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["candidates"]
    # El modelo del elemento va insertado, no referenciado: Ollama y el modo
    # estricto de Anthropic no siempre resuelven `$ref`.
    assert "$defs" not in schema

    candidate = schema["properties"]["candidates"]["items"]
    assert candidate["additionalProperties"] is False
    assert set(candidate["required"]) == set(candidate["properties"])


def test_schema_has_no_numeric_constraints() -> None:
    """`minimum`/`maximum` no están permitidos en los modos estrictos."""
    serialized = json.dumps(response_json_schema(RULES))
    assert "minimum" not in serialized
    assert "maximum" not in serialized


def test_parses_the_canonical_shape() -> None:
    candidates = parse_analysis(json.dumps({"candidates": [CANDIDATE]}), RULES)
    assert len(candidates) == 1
    assert candidates[0].start_segment == 3


def test_accepts_a_dict_without_reserializing() -> None:
    assert len(parse_analysis({"candidates": [CANDIDATE]}, RULES)) == 1


def test_accepts_a_bare_list() -> None:
    """Algunos modelos pequeños devuelven la lista sin envolver."""
    assert len(parse_analysis(json.dumps([CANDIDATE]), RULES)) == 1


def test_accepts_json_wrapped_in_a_markdown_fence() -> None:
    fenced = f"```json\n{json.dumps({'candidates': [CANDIDATE]})}\n```"
    assert len(parse_analysis(fenced, RULES)) == 1


def test_empty_candidate_list_is_valid() -> None:
    """Que un fragmento no tenga nada bueno es una respuesta legítima."""
    assert parse_analysis(json.dumps({"candidates": []}), RULES) == []


def test_unknown_fields_are_ignored() -> None:
    payload = {"candidates": [{**CANDIDATE, "confidence": 0.9}], "notes": "irrelevante"}
    assert len(parse_analysis(json.dumps(payload), RULES)) == 1


def test_invalid_json_raises_a_domain_error() -> None:
    with pytest.raises(ExternalToolError, match="JSON válido"):
        parse_analysis("lo siento, no puedo ayudarte con eso", RULES)


def test_missing_fields_raise_a_domain_error() -> None:
    with pytest.raises(ExternalToolError, match="esquema"):
        parse_analysis(json.dumps({"candidates": [{"title": "solo el título"}]}), RULES)


def test_scalar_payload_raises_a_domain_error() -> None:
    with pytest.raises(ExternalToolError, match="inesperada"):
        parse_analysis("42", RULES)


def test_the_visual_profile_asks_for_its_own_dimensions() -> None:
    """La rúbrica visual no debe pedir `value_score` sino `payoff_score`."""
    schema = response_json_schema(rules_for(ContentProfile.VISUAL), vision=True)
    properties = schema["properties"]["candidates"]["items"]["properties"]

    assert "payoff_score" in properties
    assert "value_score" not in properties
    # Y elige bloques, no índices de segmento, porque no hay transcripción.
    assert "block" in properties
    assert "start_segment" not in properties
