"""Pedirle JSON a un proveedor, sea cual sea.

Los analizadores de la fase 4 llevan cada uno su propia copia de esta
fontanería, y para el titulado se escribió una tercera. Con el juez habría sido
la cuarta, así que aquí se queda una sola: los tres proveedores hablan distinto
—Ollama quiere el esquema en `format`, OpenAI en `response_format`, Anthropic en
`output_config`— pero lo que se les pide es siempre lo mismo.

Cada tarea decide **a qué modelo** habla. Es deliberado que no compartan uno:
analizar cuarenta minutos de transcripción son decenas de llamadas y encaja en
un modelo local, mientras que juzgar o titular es UNA llamada por proyecto que
decide qué se publica. A ese precio se puede pagar un modelo bueno aunque el
resto corra en casa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

#: Modelo por defecto de cada proveedor cuando el general no le sirve.
DEFAULT_MODELS = {
    "ollama": "qwen2.5:14b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-5",
}

#: Cómo empieza el nombre de modelo de cada proveedor. Sirve para detectar que
#: `AI_MODEL` trae el de otro y no mandarle a Anthropic un "qwen2.5:14b".
#: Ollama no entra: ahí el modelo se llama como quiera quien lo descargó.
MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    "openai": ("gpt", "o1", "o3", "o4"),
    "anthropic": ("claude",),
}

MAX_TOKENS = 8000

#: Contexto de Ollama. El de fábrica son 2048 tokens y una petición con treinta
#: candidatos no cabe ni de lejos: la respuesta saldría truncada sin avisar.
OLLAMA_CONTEXT = 16384


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """Con quién se habla para una tarea concreta."""

    provider: str
    model: str


def resolve_model(provider: str | None, model: str | None) -> ModelChoice:
    """Decide proveedor y modelo, con los generales como respaldo.

    Raises:
        ExternalToolError: si el proveedor configurado no existe.
    """
    name = (provider or settings.ai_provider).lower()
    if name not in DEFAULT_MODELS:
        raise ExternalToolError(
            f"Proveedor de IA desconocido: '{name}'",
            details={"supported": sorted(DEFAULT_MODELS)},
        )

    chosen = model or settings.ai_model
    prefixes = MODEL_PREFIXES.get(name)
    if prefixes and not chosen.startswith(prefixes):
        chosen = DEFAULT_MODELS[name]

    return ModelChoice(provider=name, model=chosen)


def ask_json(
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    choice: ModelChoice,
    temperature: float = 0.0,
    timeout_multiplier: int = 1,
) -> str:
    """Manda la petición y devuelve el JSON en crudo, sin parsear.

    Parsear es cosa de quien sabe qué esperaba; aquí solo se garantiza que hay
    texto y que el proveedor no ha fallado.

    Raises:
        ExternalToolError: si el proveedor falla o responde vacío.
    """
    timeout = settings.ai_request_timeout_seconds * max(1, timeout_multiplier)

    if choice.provider == "ollama":
        return _ask_ollama(system, user, schema, choice.model, temperature, timeout)
    if choice.provider == "openai":
        return _ask_openai(system, user, schema, choice.model, temperature, timeout)
    return _ask_anthropic(system, user, schema, choice.model, timeout)


# ------------------------------------------------------------------ privado
def _ask_ollama(
    system: str,
    user: str,
    schema: dict[str, Any],
    model: str,
    temperature: float,
    timeout: int,
) -> str:
    base_url = settings.ollama_base_url.rstrip("/")
    payload = {
        "model": model,
        "stream": False,
        "format": schema,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": temperature, "num_ctx": OLLAMA_CONTEXT},
    }

    try:
        response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content")
    except httpx.HTTPStatusError as exc:
        raise ExternalToolError(
            f"Ollama ha respondido {exc.response.status_code}",
            details={"body": exc.response.text[:500]},
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalToolError(
            f"No se ha podido contactar con Ollama en {base_url}",
            details={"error": str(exc)},
        ) from exc

    if not content:
        raise ExternalToolError("Ollama ha devuelto una respuesta vacía")
    return str(content)


def _ask_openai(
    system: str,
    user: str,
    schema: dict[str, Any],
    model: str,
    temperature: float,
    timeout: int,
) -> str:
    from openai import OpenAI, OpenAIError

    if not settings.openai_api_key:
        raise ExternalToolError("El proveedor es OpenAI pero falta OPENAI_API_KEY")

    client = OpenAI(
        api_key=settings.openai_api_key, timeout=timeout, max_retries=settings.ai_max_retries
    )
    try:
        completion = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "clipforge", "strict": True, "schema": schema},
            },
        )
    except OpenAIError as exc:
        raise ExternalToolError(
            "La llamada a OpenAI ha fallado", details={"error": str(exc)[:500]}
        ) from exc

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise ExternalToolError("OpenAI ha devuelto una respuesta vacía")
    return str(content)


def _ask_anthropic(system: str, user: str, schema: dict[str, Any], model: str, timeout: int) -> str:
    import anthropic

    if not settings.anthropic_api_key:
        raise ExternalToolError("El proveedor es Anthropic pero falta ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=float(timeout),
        max_retries=settings.ai_max_retries,
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            # Sin temperatura explícita: los tipos del SDK no la admiten junto a
            # la salida estructurada, y su valor por defecto ya sirve.
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIError as exc:
        raise ExternalToolError(
            "La llamada a Anthropic ha fallado", details={"error": str(exc)[:500]}
        ) from exc

    if message.stop_reason == "refusal":
        raise ExternalToolError("Anthropic ha rechazado la petición por sus filtros")

    content = next((block.text for block in message.content if block.type == "text"), None)
    if not content:
        raise ExternalToolError("Anthropic ha devuelto una respuesta vacía")
    return str(content)
