"""Selección del proveedor de IA configurado.

Único punto del sistema que decide qué implementación se usa. El resto del
código depende solo de `ClipAnalyzer`, así que cambiar de proveedor es cambiar
`AI_PROVIDER` en el `.env`.
"""

from __future__ import annotations

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import BlockAnalyzer, ClipAnalyzer


def get_analyzer(provider: str | None = None, model: str | None = None) -> ClipAnalyzer:
    """Construye el analizador configurado.

    Raises:
        ExternalToolError: si el proveedor no existe o le falta configuración.
    """
    name = (provider or settings.ai_provider).lower()

    if name == "ollama":
        from clipforge.services.ai.ollama_analyzer import OllamaClipAnalyzer

        return OllamaClipAnalyzer(model=model)

    if name == "openai":
        from clipforge.services.ai.openai_analyzer import OpenAIClipAnalyzer

        return OpenAIClipAnalyzer(model=model)

    if name == "anthropic":
        from clipforge.services.ai.anthropic_analyzer import AnthropicClipAnalyzer

        return AnthropicClipAnalyzer(model=model)

    raise ExternalToolError(
        f"Proveedor de IA desconocido: '{name}'",
        details={"supported": ["ollama", "openai", "anthropic"]},
    )


def get_block_analyzer(provider: str | None = None, model: str | None = None) -> BlockAnalyzer:
    """Construye el analizador visual configurado.

    Vive junto al de texto porque la decisión es la misma —qué proveedor
    hablar— aunque el contrato sea distinto.

    Raises:
        ExternalToolError: si el proveedor no existe o le falta configuración.
    """
    from clipforge.services.ai.vision_analyzer import VisionClipAnalyzer

    return VisionClipAnalyzer(provider=provider, model=model)
