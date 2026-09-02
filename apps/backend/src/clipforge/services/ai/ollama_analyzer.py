"""Análisis con un modelo local servido por Ollama.

Es la opción por defecto en local: sin clave, sin coste y sin enviar la
transcripción a un tercero. Ollama admite salida estructurada pasando el
esquema JSON en el campo `format`.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisWindow,
    ClipAnalyzer,
    ClipSuggestion,
)
from clipforge.services.ai.prompts import build_system_prompt, build_user_prompt
from clipforge.services.ai.resolver import resolve_candidates
from clipforge.services.ai.schema import (
    RawClipCandidate,
    parse_analysis,
    response_json_schema,
)

logger = get_logger(__name__)

#: Espera entre reintentos. Los modelos locales fallan de forma esporádica y
#: un reintento inmediato suele bastar; no hace falta un backoff agresivo.
RETRY_BACKOFF_SECONDS = 1.0


class OllamaClipAnalyzer(ClipAnalyzer):
    """Implementación de `ClipAnalyzer` sobre la API de Ollama."""

    provider = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or settings.ai_model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def analyze_window(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[ClipSuggestion]:
        """Analiza la ventana reintentando los fallos esporádicos del modelo.

        A diferencia de los SDK de OpenAI y Anthropic, que reintentan por su
        cuenta, aquí hablamos con Ollama por HTTP directo. Un modelo local
        devuelve de vez en cuando una respuesta truncada o inservible, y perder
        una ventana entera por eso deja fuera del análisis varios minutos de
        vídeo.
        """
        attempts = max(1, settings.ai_max_retries)
        last_error: ExternalToolError | None = None

        for attempt in range(1, attempts + 1):
            try:
                raw_candidates = self._request_candidates(window, context)
            except ExternalToolError as exc:
                last_error = exc
                if attempt < attempts:
                    logger.warning(
                        "ai.window_retry",
                        window=window.number,
                        attempt=attempt,
                        error=exc.message,
                    )
                    time.sleep(RETRY_BACKOFF_SECONDS)
                continue

            logger.info(
                "ai.window_analyzed",
                provider=self.provider,
                model=self.model,
                window=window.number,
                proposed=len(raw_candidates),
                attempts=attempt,
            )
            return resolve_candidates(raw_candidates, window)

        assert last_error is not None
        raise last_error

    def _request_candidates(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[RawClipCandidate]:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": response_json_schema(),
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": build_user_prompt(window, context)},
            ],
            "options": {
                # Determinista: dos ejecuciones sobre la misma transcripción
                # deben dar el mismo ranking, o depurar es imposible.
                "temperature": 0,
                # Ventanas grandes más el prompt no caben en el contexto por
                # defecto de Ollama (2048 tokens) y la respuesta saldría truncada.
                "num_ctx": 16384,
            },
        }

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=settings.ai_request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ExternalToolError(
                f"Ollama ha respondido {exc.response.status_code}",
                details={"body": exc.response.text[:500]},
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalToolError(
                f"No se ha podido contactar con Ollama en {self.base_url}. "
                "¿Está arrancado? (`ollama serve`)",
                details={"error": str(exc)},
            ) from exc

        content = (body.get("message") or {}).get("content")
        if not content:
            raise ExternalToolError("Ollama ha devuelto una respuesta vacía")

        return parse_analysis(content)
