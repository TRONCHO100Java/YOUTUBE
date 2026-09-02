"""Análisis con la API de Anthropic (Claude)."""

from __future__ import annotations

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
from clipforge.services.ai.schema import parse_analysis, response_json_schema

logger = get_logger(__name__)

#: Modelo por defecto si AI_MODEL trae el nombre de otro proveedor.
DEFAULT_MODEL = "claude-opus-5"

#: Suficiente para varios candidatos con su justificación.
MAX_TOKENS = 16000


class AnthropicClipAnalyzer(ClipAnalyzer):
    """Implementación de `ClipAnalyzer` sobre la Messages API de Anthropic."""

    provider = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise ExternalToolError(
                "AI_PROVIDER=anthropic pero falta ANTHROPIC_API_KEY en el entorno"
            )
        configured = model or settings.ai_model
        # AI_MODEL es común a todos los proveedores; si trae un modelo de otro
        # (gpt-..., qwen...), se usa el de Anthropic por defecto.
        self.model = configured if configured.startswith("claude") else DEFAULT_MODEL
        self._api_key = key

    def analyze_window(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[ClipSuggestion]:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=float(settings.ai_request_timeout_seconds),
            max_retries=settings.ai_max_retries,
        )

        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=build_system_prompt(),
                messages=[{"role": "user", "content": build_user_prompt(window, context)}],
                output_config={"format": {"type": "json_schema", "schema": response_json_schema()}},
            )
        except anthropic.APIError as exc:
            raise ExternalToolError(
                "La llamada a Anthropic ha fallado", details={"error": str(exc)[:500]}
            ) from exc

        # Las clasificaciones de seguridad pueden rechazar una petición con un
        # 200 y stop_reason "refusal": hay que comprobarlo antes de leer content.
        if message.stop_reason == "refusal":
            raise ExternalToolError(
                "Anthropic ha rechazado la petición por sus filtros de seguridad"
            )

        content = next((block.text for block in message.content if block.type == "text"), None)
        if not content:
            raise ExternalToolError("Anthropic ha devuelto una respuesta vacía")

        raw_candidates = parse_analysis(content)
        logger.info(
            "ai.window_analyzed",
            provider=self.provider,
            model=self.model,
            window=window.number,
            proposed=len(raw_candidates),
        )
        return resolve_candidates(raw_candidates, window)
