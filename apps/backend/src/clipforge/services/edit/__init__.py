"""Montaje del clip: qué tramos del original sobreviven y en qué orden.

Separado de `services/video/`, que es quien habla con ffmpeg. Aquí se decide
QUÉ hacer; allí, cómo ejecutarlo.
"""

from clipforge.services.edit.effects import (
    Peak,
    PunchIn,
    PunchRules,
    peaks_from_signals,
    plan_punch_ins,
    zoompan_filter,
)
from clipforge.services.edit.plan import Beat, EditPlan
from clipforge.services.edit.trim import TrimRules, Word, plan_trim, words_from_segments

__all__ = [
    "Beat",
    "EditPlan",
    "Peak",
    "PunchIn",
    "PunchRules",
    "TrimRules",
    "Word",
    "peaks_from_signals",
    "plan_punch_ins",
    "plan_trim",
    "words_from_segments",
    "zoompan_filter",
]
