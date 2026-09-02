"""Análisis de viralidad con IA.

El pipeline depende solo de `ClipAnalyzer` y `select_clips`; qué proveedor hay
detrás lo decide `factory.get_analyzer()` a partir de `AI_PROVIDER`.
"""

from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisSegment,
    AnalysisWindow,
    ClipAnalyzer,
    ClipScores,
    ClipSuggestion,
)
from clipforge.services.ai.factory import get_analyzer
from clipforge.services.ai.selector import select_clips

__all__ = [
    "AnalysisContext",
    "AnalysisSegment",
    "AnalysisWindow",
    "ClipAnalyzer",
    "ClipScores",
    "ClipSuggestion",
    "get_analyzer",
    "select_clips",
]
