"""Análisis de viralidad con IA.

El pipeline depende solo de los contratos (`ClipAnalyzer` para transcripción,
`BlockAnalyzer` para fotogramas) y de las funciones de selección; qué proveedor
hay detrás lo deciden `factory.get_analyzer()` y `factory.get_block_analyzer()`
a partir de `AI_PROVIDER` y `AI_VISION_PROVIDER`.
"""

from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisSegment,
    AnalysisWindow,
    BlockAnalyzer,
    ClipAnalyzer,
    ClipScores,
    ClipSuggestion,
)
from clipforge.services.ai.factory import get_analyzer, get_block_analyzer
from clipforge.services.ai.profiles import ProfileRules, detect_profile, rules_for
from clipforge.services.ai.selector import (
    select_clips,
    select_clips_from_blocks,
    suggestions_from_signals,
)

__all__ = [
    "AnalysisContext",
    "AnalysisSegment",
    "AnalysisWindow",
    "BlockAnalyzer",
    "ClipAnalyzer",
    "ClipScores",
    "ClipSuggestion",
    "ProfileRules",
    "detect_profile",
    "get_analyzer",
    "get_block_analyzer",
    "rules_for",
    "select_clips",
    "select_clips_from_blocks",
    "suggestions_from_signals",
]
