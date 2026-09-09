"""Colocación de la ventana vertical sobre el sujeto.

Todo lo que se prueba aquí es aritmética sobre matrices: no hace falta ffmpeg,
ni OpenCV, ni un vídeo. La parte que sí necesita ffmpeg (sacar los fotogramas)
está aislada en `sample_frames` y no se prueba aquí.

El caso que da sentido al módulo entero es
`test_two_subjects_do_not_frame_the_gap`: con dos personas en los extremos del
plano, el punto medio cae entre las dos y la ventana no coge a ninguna.
"""

from __future__ import annotations

import numpy as np
import pytest

from clipforge.core.config import settings
from clipforge.services.video.crop import CropWindow, center_crop_within
from clipforge.services.video.framing import (
    CropPlan,
    FocusSample,
    FocusSource,
    FocusTrack,
    _clamp_even,
    _piecewise_expression,
    _smooth,
    _thin,
    best_offset,
    motion_weights,
    plan_crop,
)


@pytest.fixture(autouse=True)
def fixed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ajustes fijos: los tests no deben depender del .env de la máquina."""
    monkeypatch.setattr(settings, "smart_crop", True)
    monkeypatch.setattr(settings, "smart_crop_pan", False)
    monkeypatch.setattr(settings, "smart_crop_pan_ratio", 0.6)
    monkeypatch.setattr(settings, "smart_crop_max_keyframes", 12)
    monkeypatch.setattr(settings, "output_width", 1080)
    monkeypatch.setattr(settings, "output_height", 1920)


def _track(profile: np.ndarray, *, samples: list[FocusSample] | None = None) -> FocusTrack:
    return FocusTrack(
        samples=samples or [],
        profile=profile,
        scale=1.0,
        source=FocusSource.MOTION,
    )


# ------------------------------------------------------------- franja con más peso
def test_the_window_lands_on_the_busiest_strip() -> None:
    profile = np.zeros(1000)
    profile[700:800] = 10.0

    assert best_offset(profile, window=100) == pytest.approx(700, abs=5)


def test_two_subjects_do_not_frame_the_gap() -> None:
    """El motivo de existir del módulo.

    Dos personas en los extremos: el punto medio cae en el hueco entre ambas y
    la ventana no cogería a ninguna. Buscando la franja con más peso, coge una.
    """
    profile = np.zeros(1000)
    profile[100:180] = 8.0  # sujeto izquierdo
    profile[820:900] = 10.0  # sujeto derecho, algo más importante

    offset = best_offset(profile, window=200)

    assert offset is not None
    centro_hueco = 500 - 100
    assert abs(offset - centro_hueco) > 200  # no se queda en el valle
    assert 700 <= offset <= 820  # cubre al sujeto derecho


def test_a_flat_profile_refuses_to_decide() -> None:
    """Sin relieve, elegir sería inventarse una decisión: mejor centrar."""
    assert best_offset(np.ones(500), window=100) is None


def test_an_empty_profile_decides_nothing() -> None:
    assert best_offset(np.zeros(500), window=100) is None
    assert best_offset(np.empty(0), window=100) is None


def test_a_window_wider_than_the_frame_starts_at_zero() -> None:
    assert best_offset(np.ones(100), window=500) == 0


# ------------------------------------------------------------------- movimiento
def test_motion_is_measured_where_something_changed() -> None:
    previous = np.zeros((50, 200), dtype=np.uint8)
    current = previous.copy()
    current[:, 150:170] = 255

    weights = motion_weights(previous, current)

    assert weights is not None
    assert weights[160] > 0
    assert weights[10] == 0


def test_compression_noise_is_not_motion() -> None:
    """Un ruido de ±5 repartido por todo el fotograma aplanaría el perfil."""
    previous = np.full((50, 200), 100, dtype=np.uint8)
    current = np.full((50, 200), 104, dtype=np.uint8)

    assert motion_weights(previous, current) is None


def test_identical_frames_have_no_motion() -> None:
    frame = np.full((10, 20), 128, dtype=np.uint8)
    assert motion_weights(frame, frame.copy()) is None


def test_mismatched_frames_are_rejected() -> None:
    assert motion_weights(np.zeros((10, 20), np.uint8), np.zeros((10, 30), np.uint8)) is None


# ------------------------------------------------------------------------ plan
def test_without_signal_the_window_is_centered() -> None:
    content = CropWindow(x=0, y=0, width=1920, height=1080)

    plan = plan_crop(_track(np.empty(0)), content, target_width=1080, target_height=1920)

    assert plan.source is FocusSource.CENTER
    assert plan.keyframes == ()
    # El centrado de siempre: (1920 - 606) / 2.
    assert plan.window.x == 656


def test_the_window_moves_onto_the_subject() -> None:
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    profile = np.zeros(1920)
    profile[200:500] = 5.0

    plan = plan_crop(_track(profile), content, target_width=1080, target_height=1920)

    assert plan.window.x < 400  # se va a la izquierda, donde está el sujeto
    assert plan.window.width == 606


def test_the_window_never_leaves_the_content_area() -> None:
    """Con letterbox incrustado, salirse metería barras negras en el clip."""
    content = CropWindow(x=240, y=0, width=1440, height=1080)
    profile = np.zeros(1920)
    profile[1850:1920] = 9.0  # sujeto pegado al borde derecho

    plan = plan_crop(_track(profile), content, target_width=1080, target_height=1920)

    assert plan.window.x >= content.x
    assert plan.window.x + plan.window.width <= content.x + content.width


def test_the_offset_is_always_even() -> None:
    """Un desplazamiento impar descoloca el croma en 4:2:0."""
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    profile = np.zeros(1920)
    profile[333:777] = 3.0

    plan = plan_crop(_track(profile), content, target_width=1080, target_height=1920)

    assert plan.window.x % 2 == 0


def test_panning_is_off_by_default() -> None:
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    profile = np.zeros(1920)
    profile[100:300] = 4.0
    samples = [
        FocusSample(time=float(i), x=float(i * 100), source=FocusSource.MOTION) for i in range(10)
    ]

    plan = plan_crop(
        _track(profile, samples=samples), content, target_width=1080, target_height=1920
    )

    assert plan.keyframes == ()


def test_panning_needs_real_travel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Moverse por unos píxeles marea más de lo que aporta."""
    monkeypatch.setattr(settings, "smart_crop_pan", True)
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    profile = np.zeros(1920)
    profile[100:300] = 4.0
    quietos = [
        FocusSample(time=float(i), x=200.0 + i, source=FocusSource.MOTION) for i in range(10)
    ]

    plan = plan_crop(
        _track(profile, samples=quietos), content, target_width=1080, target_height=1920
    )

    assert plan.keyframes == ()


def test_a_travelling_subject_produces_keyframes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "smart_crop_pan", True)
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    profile = np.zeros(1920)
    profile[100:300] = 4.0
    viajeros = [
        FocusSample(time=float(i), x=float(i * 130), source=FocusSource.MOTION) for i in range(10)
    ]

    plan = plan_crop(
        _track(profile, samples=viajeros), content, target_width=1080, target_height=1920
    )

    assert len(plan.keyframes) > 1
    assert all(x % 2 == 0 for _t, x in plan.keyframes)


# ------------------------------------------------------------------ expresión
def test_a_single_keyframe_is_a_plain_number() -> None:
    assert _piecewise_expression(((0.0, 300),)) == "300"


def test_the_expression_interpolates_between_keyframes() -> None:
    expression = _piecewise_expression(((0.0, 100), (2.0, 300)))

    assert "lt(t,2.000)" in expression
    assert "100+(200)" in expression


def test_the_expression_is_quoted_because_it_has_commas() -> None:
    """Sin comillas, las comas de `if(...)` separarían filtros del filtrograma."""
    expression = _piecewise_expression(((0.0, 100), (2.0, 300)))

    assert expression.startswith("'")
    assert expression.endswith("'")
    assert "," in expression


def test_the_expression_keeps_the_offset_even() -> None:
    assert "2*floor(" in _piecewise_expression(((0.0, 100), (2.0, 300)))


def test_a_static_plan_renders_the_simple_filter() -> None:
    plan = CropPlan(window=CropWindow(x=656, y=0, width=606, height=1080))
    assert plan.to_filter() == "crop=606:1080:656:0"


def test_a_pan_plan_renders_an_expression() -> None:
    plan = CropPlan(
        window=CropWindow(x=0, y=0, width=606, height=1080),
        keyframes=((0.0, 100), (5.0, 900)),
    )
    rendered = plan.to_filter()

    assert rendered.startswith("crop=606:1080:'")
    assert rendered.endswith(":0")


# -------------------------------------------------------------------- utilidades
def test_smoothing_removes_the_jitter() -> None:
    samples = [
        FocusSample(time=float(i), x=500.0 + (30 if i % 2 else -30), source=FocusSource.FACE)
        for i in range(10)
    ]

    smoothed = _smooth(samples, window=5)

    interiores = [s.x for s in smoothed[2:-2]]
    assert max(interiores) - min(interiores) < 30


def test_smoothing_leaves_a_short_track_alone() -> None:
    samples = [FocusSample(time=0.0, x=1.0, source=FocusSource.FACE)]
    assert _smooth(samples, window=5) is samples


def test_thinning_respects_the_limit() -> None:
    samples = [
        FocusSample(time=float(i), x=float(i), source=FocusSource.MOTION) for i in range(100)
    ]

    thinned = _thin(samples, 12)

    assert len(thinned) <= 12
    assert thinned[0].time == 0.0
    assert thinned[-1].time == 99.0


@pytest.mark.parametrize(
    ("value", "low", "high", "expected"),
    [
        (155.7, 0, 1000, 154),
        (-50.0, 10, 900, 10),
        (9999.0, 10, 900, 900),
        (0.0, 0, 100, 0),
    ],
)
def test_clamping_stays_in_range_and_even(value: float, low: int, high: int, expected: int) -> None:
    result = _clamp_even(value, low, high)

    assert result == expected
    assert result % 2 == 0


def test_travel_measures_the_full_span() -> None:
    samples = [
        FocusSample(time=0.0, x=100.0, source=FocusSource.MOTION),
        FocusSample(time=1.0, x=800.0, source=FocusSource.MOTION),
        FocusSample(time=2.0, x=400.0, source=FocusSource.MOTION),
    ]

    assert _track(np.empty(0), samples=samples).travel == 700.0


# ------------------------------------------------------- corrección del usuario
def test_a_manual_offset_is_kept_exactly() -> None:
    """Si alguien ha movido el encuadre, recalcularlo le desharía el trabajo."""
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    centered = center_crop_within(content, 1080, 1920)

    plan = CropPlan(
        window=CropWindow(x=1000, y=centered.y, width=centered.width, height=centered.height),
        source=FocusSource.MANUAL,
    )

    assert plan.source is FocusSource.MANUAL
    assert plan.to_filter() == f"crop={centered.width}:{centered.height}:1000:{centered.y}"


def test_manual_is_a_source_of_its_own() -> None:
    """No es ni cara, ni movimiento, ni centro: lo decidió una persona."""
    assert FocusSource.MANUAL.value == "manual"
    assert FocusSource.MANUAL not in (FocusSource.FACE, FocusSource.MOTION, FocusSource.CENTER)
