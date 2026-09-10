"""Montaje del clip: qué tramos del original sobreviven y en qué orden.

Separado de `services/video/`, que es quien habla con ffmpeg. Aquí se decide
QUÉ hacer; allí, cómo ejecutarlo.
"""

from clipforge.services.edit.plan import Beat, EditPlan
from clipforge.services.edit.trim import TrimRules, Word, plan_trim, words_from_segments

__all__ = [
    "Beat",
    "EditPlan",
    "TrimRules",
    "Word",
    "plan_trim",
    "words_from_segments",
]
