"""Los acercamientos se colocan donde se ha medido un golpe, no donde se cree.

La regla que gobierna este módulo: un efecto mal puesto es peor que ningún
efecto. Todo lo que se prueba aquí es que no se ponen de más, ni pegados, ni
encima del gancho, ni sobre un golpe que ya se ha eliminado del montaje.
"""

from __future__ import annotations

from clipforge.services.edit import Beat, EditPlan, Peak, PunchRules, plan_punch_ins
from clipforge.services.edit.effects import (
    peaks_from_signals,
    zoom_expression,
    zoompan_filter,
)

RULES = PunchRules(min_prominence=0.45, max_punches=3, min_spacing=5.0, edge_margin=1.5)


def clip(seconds: float = 40.0) -> EditPlan:
    return EditPlan.single(100.0, 100.0 + seconds)


def peak(at: float, prominence: float = 0.9) -> Peak:
    """Un pico en tiempos del original, sobre un clip que empieza en 100."""
    return Peak(time=100.0 + at, prominence=prominence)


# ------------------------------------------------------------------ colocar
def test_a_loud_moment_gets_a_punch_in() -> None:
    punches = plan_punch_ins(clip(), [peak(12.0)], rules=RULES)

    assert len(punches) == 1
    assert punches[0].at == 12.0


def test_normal_conversation_gets_nothing() -> None:
    """Por debajo del umbral no hay golpe: hay gente hablando."""
    assert plan_punch_ins(clip(), [peak(12.0, prominence=0.1)], rules=RULES) == ()


def test_no_peaks_no_effects() -> None:
    assert plan_punch_ins(clip(), [], rules=RULES) == ()


def test_two_peaks_together_only_earn_one() -> None:
    """Dos acercamientos seguidos son un temblor, no un énfasis."""
    punches = plan_punch_ins(clip(), [peak(12.0), peak(13.5)], rules=RULES)

    assert len(punches) == 1


def test_the_loudest_of_a_group_is_the_one_that_wins() -> None:
    punches = plan_punch_ins(
        clip(), [peak(12.0, prominence=0.5), peak(13.5, prominence=0.95)], rules=RULES
    )

    assert punches[0].at == 13.5


def test_there_is_a_ceiling_per_clip() -> None:
    """Si todo se subraya, no se subraya nada."""
    peaks = [peak(float(second)) for second in range(3, 38, 6)]

    assert len(plan_punch_ins(clip(), peaks, rules=RULES)) <= RULES.max_punches


def test_the_hook_keeps_a_clean_frame() -> None:
    """El primer segundo lo ocupa el gancho y ahí no se mueve la cámara."""
    assert plan_punch_ins(clip(), [peak(0.4)], rules=RULES) == ()


def test_the_ending_is_left_alone() -> None:
    """El último segundo es el remate: moverlo lo estropea."""
    assert plan_punch_ins(clip(40.0), [peak(39.6)], rules=RULES) == ()


def test_a_clip_too_short_to_breathe_gets_no_effects() -> None:
    assert plan_punch_ins(clip(2.0), [peak(1.0)], rules=RULES) == ()


def test_the_punches_come_out_in_the_order_they_happen() -> None:
    punches = plan_punch_ins(clip(), [peak(30.0), peak(10.0), peak(20.0)], rules=RULES)

    assert [punch.at for punch in punches] == [10.0, 20.0, 30.0]


# ------------------------------------------------------- después de cortar
def test_a_peak_is_placed_where_it_ends_up_after_trimming() -> None:
    """El golpe se adelanta si antes se ha quitado un silencio."""
    edit = EditPlan.of([Beat(100.0, 105.0), Beat(110.0, 120.0)])

    (punch,) = plan_punch_ins(edit, [peak(12.0)], rules=RULES)

    # Segundo 112 del original, cinco segundos de corte por delante -> 7.
    assert punch.at == 7.0


def test_a_peak_inside_a_cut_no_longer_exists() -> None:
    """El golpe que lo justificaba ya no está en el vídeo."""
    edit = EditPlan.of([Beat(100.0, 105.0), Beat(110.0, 120.0)])

    assert plan_punch_ins(edit, [peak(7.0)], rules=RULES) == ()


# ------------------------------------------------------------- la expresión
def test_without_punches_the_zoom_is_flat() -> None:
    assert zoom_expression((), fps=30.0) == "1"


def test_the_zoom_ramps_up_and_down() -> None:
    """Sin rampas el zoom entra de golpe y se lee como un fallo."""
    (punch,) = plan_punch_ins(clip(), [peak(12.0)], rules=RULES)
    expression = zoom_expression([punch], fps=30.0)

    assert "between" in expression
    assert str(round(punch.start, 3)) in expression
    assert str(round(punch.end, 3)) in expression


def test_the_filter_declares_the_output_size() -> None:
    """`zoompan` cambia el tamaño si no se le dice: el clip saldría torcido."""
    (punch,) = plan_punch_ins(clip(), [peak(12.0)], rules=RULES)

    assert "s=1080x1920" in zoompan_filter([punch], width=1080, height=1920, fps=30.0)


def test_one_frame_per_frame() -> None:
    """`zoompan` nació para fotos fijas: sin d=1 deja el vídeo a cámara lenta."""
    assert "d=1" in zoompan_filter((), width=1080, height=1920, fps=30.0)


# ----------------------------------------------------- lo que hay guardado
def test_the_peaks_stored_by_the_pipeline_are_read() -> None:
    peaks = peaks_from_signals([{"t": 12.5, "db": -14.0, "p": 0.8}])

    assert peaks[0].time == 12.5
    assert peaks[0].prominence == 0.8


def test_a_peak_without_a_time_is_skipped() -> None:
    """Colocaría un acercamiento en el segundo cero, encima del gancho."""
    assert peaks_from_signals([{"db": -14.0}]) == []


def test_a_peak_without_prominence_counts_as_none() -> None:
    assert peaks_from_signals([{"t": 5.0}])[0].prominence == 0.0
