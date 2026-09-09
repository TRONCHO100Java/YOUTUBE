"""Construcción y puntuación de bloques a partir de las señales.

Es la lógica que sustituye a la transcripción cuando el vídeo no habla, así que
merece la misma cobertura que el troceado de texto. Todo esto es aritmética
pura: no hace falta ffmpeg, ni GPU, ni un modelo.

Los números de varios casos salen del vídeo que motivó la fase: una
recopilación de comedia bengalí de 519 s en la que Whisper produjo tres
segmentos y quince caracteres.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from clipforge.services.signals.base import (
    EnergyPeak,
    SamplePoint,
    SignalTimeline,
    downsample,
    normalize,
    parse_metadata_stream,
)
from clipforge.services.signals.blocks import (
    build_blocks,
    duration_fit,
    rank_blocks,
    segment_by_cuts,
)

#: Cortes reales detectados en el vídeo de referencia, en segundos.
REAL_CUTS = [
    104.5,
    106.8,
    110.1,
    112.4,
    113.8,
    117.4,
    130.6,
    161.1,
    164.5,
    184.6,
    253.5,
    278.3,
    281.1,
    320.0,
    323.1,
    325.6,
    328.8,
    344.6,
    347.7,
    354.4,
    355.2,
    357.8,
    362.2,
    366.1,
    378.9,
    383.1,
    398.1,
    400.8,
    422.6,
    426.8,
    430.0,
    434.2,
    439.1,
    442.9,
    472.6,
]
REAL_DURATION = 519.4


# ------------------------------------------------------------------ troceado
def test_a_video_without_cuts_is_still_split() -> None:
    """Sin cortes detectados, el vídeo se reparte en tramos regulares."""
    spans = segment_by_cuts([], 300.0, min_duration=10, max_duration=60)

    assert len(spans) == 5
    assert all(10 <= end - start <= 60 for start, end in spans)
    assert spans[0][0] == 0.0
    assert spans[-1][1] == pytest.approx(300.0)


def test_short_spans_are_merged_until_they_are_publishable() -> None:
    """Una ráfaga de planos de dos segundos es un solo gag, no diez clips."""
    cuts = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]
    spans = segment_by_cuts(cuts, 40.0, min_duration=10, max_duration=60)

    assert all(end - start >= 10 for start, end in spans)


def test_long_spans_are_split_into_equal_parts() -> None:
    """Repartir en partes iguales evita dejar una cola inservible al final."""
    spans = segment_by_cuts([], 100.0, min_duration=10, max_duration=60)

    assert len(spans) == 2
    durations = [end - start for start, end in spans]
    assert durations == pytest.approx([50.0, 50.0])


def test_spans_cover_the_whole_video_without_gaps() -> None:
    spans = segment_by_cuts(REAL_CUTS, REAL_DURATION, min_duration=10, max_duration=60)

    assert spans[0][0] == 0.0
    assert spans[-1][1] == pytest.approx(REAL_DURATION)
    for (_, end), (next_start, _) in pairwise(spans):
        assert end == pytest.approx(next_start)


def test_the_reference_video_yields_usable_blocks() -> None:
    """Donde el análisis de texto encontró cero, esto encuentra tramos reales."""
    spans = segment_by_cuts(REAL_CUTS, REAL_DURATION, min_duration=10, max_duration=60)

    assert len(spans) >= 10
    assert all(10 <= end - start <= 60 for start, end in spans)


def test_cuts_outside_the_video_are_ignored() -> None:
    spans = segment_by_cuts([-5.0, 10.0, 999.0], 30.0, min_duration=5, max_duration=30)

    assert spans[0] == (0.0, 10.0)
    assert spans[-1][1] == pytest.approx(30.0)


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_a_video_without_duration_yields_nothing(duration: float) -> None:
    assert segment_by_cuts([1.0], duration, min_duration=5, max_duration=30) == []


def test_inconsistent_limits_are_rejected() -> None:
    with pytest.raises(ValueError, match="min_duration"):
        segment_by_cuts([], 100.0, min_duration=60, max_duration=10)


# ---------------------------------------------------------------- puntuación
def _flat(times: list[float], value: float) -> list[SamplePoint]:
    return [SamplePoint(time=t, value=value) for t in times]


def test_the_loudest_block_scores_highest() -> None:
    spans = [(0.0, 30.0), (30.0, 60.0)]
    energy = _flat([5.0, 15.0, 25.0], -30.0) + _flat([35.0, 45.0, 55.0], -10.0)

    blocks = build_blocks(spans, energy=energy, target_duration=30)

    assert blocks[1].score > blocks[0].score
    assert blocks[1].energy == 1.0
    assert blocks[0].energy == 0.0


def test_peaks_inside_a_block_are_counted() -> None:
    spans = [(0.0, 30.0), (30.0, 60.0)]
    peaks = [EnergyPeak(t, -12.0, 0.8) for t in (31.0, 40.0, 50.0)]

    blocks = build_blocks(spans, peaks=peaks, target_duration=30)

    assert blocks[0].peaks == 0
    assert blocks[1].peaks == 3


def test_an_empty_block_does_not_look_loud() -> None:
    """Sin muestras dentro, el bloque hereda el mínimo, no un cero engañoso.

    En una curva de decibelios el cero es altísimo: tratarlo como "sin datos"
    colaría un tramo mudo como el más ruidoso del vídeo.
    """
    spans = [(0.0, 30.0), (30.0, 60.0)]
    energy = _flat([1.0, 2.0, 3.0], -40.0) + _flat([4.0, 5.0], -5.0)

    blocks = build_blocks(spans, energy=energy, target_duration=30)

    assert blocks[1].energy == 0.0  # el bloque sin muestras hereda el mínimo


def test_duration_fit_peaks_at_the_target() -> None:
    assert duration_fit(30.0, 30.0) == 1.0
    assert duration_fit(15.0, 30.0) == pytest.approx(0.5)
    assert duration_fit(90.0, 30.0) == 0.0  # nunca negativo


def test_ranking_is_deterministic() -> None:
    """Dos ejecuciones sobre el mismo vídeo deben dar el mismo orden."""
    spans = [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0)]
    blocks = build_blocks(spans, target_duration=30)

    assert [b.start for b in rank_blocks(blocks)] == [b.start for b in rank_blocks(blocks)]
    # A igualdad de puntuación manda el más temprano.
    assert rank_blocks(blocks)[0].start == 0.0


def test_ranking_honours_the_limit() -> None:
    spans = [(float(i) * 30, float(i + 1) * 30) for i in range(10)]
    blocks = build_blocks(spans, target_duration=30)

    assert len(rank_blocks(blocks, limit=3)) == 3


def test_no_spans_means_no_blocks() -> None:
    assert build_blocks([], target_duration=30) == []


# ------------------------------------------------------------------ parseo
def test_metadata_output_is_parsed_into_a_series() -> None:
    text = (
        "frame:0    pts:0       pts_time:0\n"
        "lavfi.astats.Overall.RMS_level=-18.387442\n"
        "frame:1    pts:16000   pts_time:1\n"
        "lavfi.astats.Overall.RMS_level=-18.648933\n"
    )
    points = parse_metadata_stream(text)

    assert [p.time for p in points] == [0.0, 1.0]
    assert points[0].value == pytest.approx(-18.387442)


def test_silence_becomes_a_number_instead_of_a_hole() -> None:
    """ffmpeg escribe `-inf` en un silencio absoluto, que no es serializable."""
    text = "frame:0 pts_time:0\nlavfi.astats.Overall.RMS_level=-inf\n"
    [point] = parse_metadata_stream(text)

    assert point.value == -90.0


def test_the_first_difference_frame_is_not_a_hole_either() -> None:
    """El primer fotograma de una diferencia no tiene con qué compararse."""
    text = "frame:0 pts_time:0\nlavfi.signalstats.YAVG=nan\n"
    [point] = parse_metadata_stream(text)

    assert point.value == 0.0


# ------------------------------------------------------- curvas y serialización
def test_downsampling_keeps_the_peaks() -> None:
    """Promediar aplanaría la curva justo donde la señal importa."""
    points = [SamplePoint(float(i), 0.0) for i in range(100)]
    points[42] = SamplePoint(42.0, 99.0)

    reduced = downsample(points, 10)

    assert len(reduced) == 10
    assert max(p.value for p in reduced) == 99.0


def test_downsampling_leaves_short_series_alone() -> None:
    points = [SamplePoint(float(i), 1.0) for i in range(5)]
    assert downsample(points, 10) is points


def test_normalize_stays_inside_the_range() -> None:
    assert normalize(5.0, 0.0, 10.0) == 0.5
    assert normalize(-1.0, 0.0, 10.0) == 0.0
    assert normalize(99.0, 0.0, 10.0) == 1.0
    assert normalize(5.0, 3.0, 3.0) == 0.0  # rango degenerado


def test_a_timeline_survives_a_round_trip_through_json() -> None:
    """Se guarda en JSONB y se lee desde el editor: tiene que volver igual."""
    spans = [(0.0, 30.0), (30.0, 60.0)]
    original = SignalTimeline(
        duration=60.0,
        energy=[SamplePoint(1.0, -20.0)],
        peaks=[EnergyPeak(15.0, -12.0, 0.9)],
        cuts=[30.0],
        motion=[SamplePoint(1.0, 4.5)],
        blocks=build_blocks(spans, target_duration=30),
    )

    restored = SignalTimeline.from_dict(original.to_dict())

    assert restored.duration == 60.0
    assert restored.cuts == [30.0]
    assert restored.peaks[0].time == 15.0
    assert [b.start for b in restored.blocks] == [b.start for b in original.blocks]
