"""Detección del perfil de contenido y rúbrica de cada uno.

El caso que motivó todo esto está aquí como test: un vídeo de 519 s del que
Whisper sacó 4,5 segundos de habla alucinada. Con la rúbrica de pódcast, ese
vídeo no podía puntuar; con la visual, sí.
"""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.db.models.enums import ContentProfile
from clipforge.services.ai.profiles import detect_profile, rules_for
from clipforge.services.ai.prompts import build_system_prompt


@pytest.fixture(autouse=True)
def auto_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detección automática: los tests no dependen del .env de la máquina."""
    monkeypatch.setattr(settings, "content_profile", "auto")
    monkeypatch.setattr(settings, "visual_speech_ratio", 0.25)
    monkeypatch.setattr(settings, "visual_chars_per_minute", 200.0)


def test_the_reference_comedy_video_is_detected_as_visual() -> None:
    """4,5 s de habla sobre 519 s de vídeo: 0,9 %."""
    profile = detect_profile(speech_seconds=4.5, text_characters=15, video_duration=519.4)

    assert profile is ContentProfile.VISUAL


def test_a_podcast_is_detected_as_talking() -> None:
    profile = detect_profile(speech_seconds=3400.0, text_characters=52000, video_duration=3600.0)

    assert profile is ContentProfile.TALKING


def test_dense_speech_over_a_short_video_is_still_talking() -> None:
    profile = detect_profile(speech_seconds=50.0, text_characters=900, video_duration=60.0)

    assert profile is ContentProfile.TALKING


def test_a_high_ratio_with_almost_no_text_is_visual() -> None:
    """Tres palabras sueltas en un vídeo corto dan un ratio engañosamente alto.

    Por eso hacen falta los dos criterios: basta con que falle uno.
    """
    profile = detect_profile(speech_seconds=20.0, text_characters=12, video_duration=30.0)

    assert profile is ContentProfile.VISUAL


def test_a_video_without_duration_does_not_crash() -> None:
    assert detect_profile(speech_seconds=0.0, text_characters=0, video_duration=0.0) is (
        ContentProfile.TALKING
    )


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("talking", ContentProfile.TALKING), ("visual", ContentProfile.VISUAL)],
)
def test_an_explicit_setting_beats_the_detection(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: ContentProfile
) -> None:
    monkeypatch.setattr(settings, "content_profile", configured)

    # Datos que apuntarían al perfil contrario.
    profile = detect_profile(speech_seconds=4.5, text_characters=15, video_duration=519.4)
    assert profile is expected


# ------------------------------------------------------------------ rúbricas
@pytest.mark.parametrize("profile", list(ContentProfile))
def test_every_rubric_adds_up_to_a_hundred(profile: ContentProfile) -> None:
    """El total del candidato es la suma de sus dimensiones: deben sumar 100."""
    assert rules_for(profile).total_maximum == 100


@pytest.mark.parametrize("profile", list(ContentProfile))
def test_every_dimension_maps_to_a_real_column(profile: ContentProfile) -> None:
    """Las columnas de puntuación de la tabla son siete y fijas."""
    columns = {
        "hook",
        "curiosity",
        "emotion",
        "clarity",
        "value",
        "shareability",
        "duration",
    }
    rules = rules_for(profile)

    assert {dimension.column for dimension in rules.dimensions} <= columns
    # Y ninguna columna se usa dos veces, o una dimensión pisaría a la otra.
    used = [dimension.column for dimension in rules.dimensions]
    assert len(used) == len(set(used))


def test_the_visual_rubric_does_not_ask_for_quotes() -> None:
    """Exigir una cita textual en un vídeo sin diálogo es pedir un imposible."""
    prompt = build_system_prompt(rules_for(ContentProfile.VISUAL), vision=True)

    assert "segmento inicial" not in prompt
    assert "payoff_score" in prompt
    assert "value_score" not in prompt


def test_the_talking_rubric_keeps_its_rules() -> None:
    prompt = build_system_prompt(rules_for(ContentProfile.TALKING))

    assert "segmento inicial" in prompt
    assert "value_score" in prompt


def test_every_prompt_demands_english_titles() -> None:
    """El título y el gancho se publican, así que van en inglés en las dos modalidades."""
    for profile, vision in (
        (ContentProfile.TALKING, False),
        (ContentProfile.VISUAL, True),
    ):
        prompt = build_system_prompt(rules_for(profile), vision=vision)

        assert "SIEMPRE EN INGLÉS" in prompt


def test_the_visual_profile_uses_shorter_clips() -> None:
    visual = rules_for(ContentProfile.VISUAL)
    talking = rules_for(ContentProfile.TALKING)

    assert visual.max_duration < talking.max_duration
    assert visual.target_duration < talking.target_duration


def test_the_visual_profile_does_not_burn_subtitles() -> None:
    """Sin diálogo utilizable, incrustar subtítulos es incrustar ruido."""
    assert rules_for(ContentProfile.VISUAL).burn_subtitles is False
