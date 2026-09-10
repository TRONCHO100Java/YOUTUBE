"""La puerta de calidad mira el MP4 terminado, no las intenciones.

Todo lo anterior comprueba que cada capa hizo su trabajo. Estos casos son los
que salen de un pipeline en el que nada ha fallado y aun así el clip no se
puede publicar.
"""

from __future__ import annotations

from clipforge.services.quality import ClipFacts, Severity, inspect_clip


def clip(**overrides: object) -> ClipFacts:
    base = {
        "duration": 30.0,
        "width": 1080,
        "height": 1920,
        "filesize_bytes": 8_000_000,
        "cues": 12,
        "has_hook": True,
    }
    return ClipFacts(**{**base, **overrides})  # type: ignore[arg-type]


def codes(**overrides: object) -> list[str]:
    return [issue.code for issue in inspect_clip(clip(**overrides)).issues]


# ------------------------------------------------------------------ el caso bueno
def test_a_good_clip_passes_without_a_word() -> None:
    report = inspect_clip(clip())

    assert report.issues == ()
    assert report.publishable is True
    assert report.summary == "Sin problemas"


# ---------------------------------------------------------------- duración
def test_a_clip_too_short_to_understand_is_stopped() -> None:
    assert "too_short" in codes(duration=4.0)
    assert inspect_clip(clip(duration=4.0)).publishable is False


def test_a_long_clip_only_gets_a_warning() -> None:
    """Largo para Shorts, pero publicable: eso lo decide quien mira."""
    report = inspect_clip(clip(duration=120.0))

    assert "too_long" in [issue.code for issue in report.issues]
    assert report.publishable is True


def test_a_normal_length_says_nothing() -> None:
    assert codes(duration=30.0) == []


# ------------------------------------------------------------------ fichero
def test_a_clip_that_came_out_black_is_caught_by_its_weight() -> None:
    """Pesa poco justamente porque no hay imagen que codificar."""
    assert "suspiciously_small" in codes(filesize_bytes=90_000)


# ------------------------------------------------------------------ formato
def test_a_clip_that_is_not_vertical_is_not_a_short() -> None:
    assert "not_vertical" in codes(width=1920, height=1080)


def test_a_square_clip_is_not_vertical_either() -> None:
    assert "not_vertical" in codes(width=1080, height=1080)


def test_a_slightly_odd_size_still_passes() -> None:
    """1080x1918 es 9:16 con dos píxeles de redondeo, no otro formato."""
    assert "not_vertical" not in codes(height=1918)


# -------------------------------------------------------------------- texto
def test_a_clip_without_a_single_word_is_the_worst_case() -> None:
    """El vídeo existe, se ve bien, y nadie entiende de qué va."""
    report = inspect_clip(clip(cues=0, has_hook=False))

    assert "no_text" in [issue.code for issue in report.issues]
    assert report.publishable is False


def test_a_visual_clip_with_only_a_hook_is_fine() -> None:
    """Un clip sin diálogo no tiene nada que subtitular, y no pasa nada."""
    assert codes(cues=0, has_hook=True, expects_speech=False) == []


def test_a_talking_clip_without_subtitles_is_worth_saying() -> None:
    report = inspect_clip(clip(cues=0, has_hook=True, expects_speech=True))

    assert [issue.code for issue in report.issues] == ["no_subtitles"]
    assert report.publishable is True


# ------------------------------------------------------------------ el aviso
def test_several_problems_come_back_together() -> None:
    """Se avisa de todo a la vez: arreglar de uno en uno es tres rondas."""
    report = inspect_clip(clip(duration=3.0, cues=0, has_hook=False))

    assert len(report.issues) == 2
    assert report.publishable is False


def test_the_summary_reads_like_a_sentence() -> None:
    summary = inspect_clip(clip(duration=3.0)).summary

    assert "3 s" in summary


def test_the_report_serialises_for_storage() -> None:
    stored = inspect_clip(clip(duration=3.0)).to_dict()

    assert stored["publishable"] is False
    assert stored["issues"][0]["severity"] == str(Severity.PROBLEM)  # type: ignore[index]
