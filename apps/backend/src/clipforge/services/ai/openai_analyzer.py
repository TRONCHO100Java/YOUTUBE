"""Análisis con la API de OpenAI."""

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
from clipforge.services.ai.profiles import rules_for
from clipforge.services.ai.prompts import build_system_prompt, build_user_prompt
from clipforge.services.ai.resolver import resolve_candidates
from clipforge.services.ai.schema import parse_analysis, response_json_schema

logger = get_logger(__name__)


class OpenAIClipAnalyzer(ClipAnalyzer):
    """Implementación de `ClipAnalyzer` sobre OpenAI con salida estructurada."""

    provider = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        key = api_key or settings.openai_api_key
        if not key:
            raise ExternalToolError("AI_PROVIDER=openai pero falta OPENAI_API_KEY en el entorno")
        self.model = model or settings.ai_model
        self._api_key = key

    def analyze_window(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[ClipSuggestion]:
        rules = rules_for(context.profile)
        from openai import OpenAI, OpenAIError

        client = OpenAI(
            api_key=self._api_key,
            timeout=settings.ai_request_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

        try:
            completion = client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": build_system_prompt(rules)},
                    {"role": "user", "content": build_user_prompt(window, context)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clip_analysis",
                        # strict garantiza que la respuesta cumple el esquema:
                        # sin esto habría que tolerar campos ausentes.
                        "strict": True,
                        "schema": response_json_schema(rules),
                    },
                },
            )
        except OpenAIError as exc:
            raise ExternalToolError(
                "La llamada a OpenAI ha fallado", details={"error": str(exc)[:500]}
            ) from exc

        content = completion.choices[0].message.content if completion.choices else None
        if not content:
            raise ExternalToolError("OpenAI ha devuelto una respuesta vacía")

        raw_candidates = parse_analysis(content, rules)
        logger.info(
            "ai.window_analyzed",
            provider=self.provider,
            model=self.model,
            window=window.number,
            proposed=len(raw_candidates),
        )
        return resolve_candidates(raw_candidates, window, rules)
