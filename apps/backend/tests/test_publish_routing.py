"""A qué canal va cada clip.

El reparto es estricto a propósito: un canal que se llena de contenido que
*casi* encaja es justo el problema que estos canales existen para evitar. Ante
la duda, el clip se queda sin canal y lo coloca una persona.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.services.publish import ClipFacts, route, route_all


@dataclass
class Channel:
    """Un canal de destino, sin base de datos de por medio."""

    name: str
    enabled: bool = True
    niche: str | None = None
    people: list[str] | None = None
    topics: list[str] | None = None
    kinds: list[str] | None = None
    min_score: float = 0.0
    priority: int = 0


def clip(**overrides: object) -> ClipFacts:
    base = {
        "score": 70.0,
        "niche": "streamers",
        "people": ("speed",),
        "topics": ("futbol",),
        "kind": "reaccion",
    }
    return ClipFacts(**{**base, **overrides})  # type: ignore[arg-type]


def chosen(facts: ClipFacts, *channels: Channel) -> str | None:
    match = route(facts, list(channels))
    return match.channel.name if match else None


# ------------------------------------------------------------------ encajar
def test_a_channel_that_asks_for_speed_gets_the_speed_clip() -> None:
    assert chosen(clip(), Channel("Speed Clips", people=["speed"])) == "Speed Clips"


def test_a_channel_that_asks_for_someone_else_does_not() -> None:
    assert chosen(clip(), Channel("Kai Clips", people=["kai cenat"])) is None


def test_one_name_of_the_list_is_enough() -> None:
    channel = Channel("Streamers USA", people=["kai cenat", "speed", "poki"])

    assert chosen(clip(), channel) == "Streamers USA"


def test_all_the_filters_have_to_match() -> None:
    """Pide Speed Y un fail: una reacción de Speed no vale."""
    channel = Channel("Speed Fails", people=["speed"], kinds=["fail"])

    assert chosen(clip(kind="reaccion"), channel) is None
    assert chosen(clip(kind="fail"), channel) == "Speed Fails"


def test_a_channel_without_filters_takes_anything() -> None:
    assert chosen(clip(), Channel("Cajón de sastre")) == "Cajón de sastre"


def test_capital_letters_do_not_break_the_match() -> None:
    """El etiquetador normaliza; lo que escribe el usuario, también."""
    assert chosen(clip(), Channel("Speed Clips", people=["Speed"])) == "Speed Clips"


def test_accents_do_not_break_it_either() -> None:
    facts = clip(topics=("motivacion",))

    assert chosen(facts, Channel("Motivación", topics=["Motivación"])) == "Motivación"


# ------------------------------------------------------------------- la nota
def test_a_channel_can_be_pickier_than_the_system() -> None:
    """Un canal principal y uno de descartes no publican lo mismo."""
    assert chosen(clip(score=55.0), Channel("Principal", min_score=70)) is None
    assert chosen(clip(score=80.0), Channel("Principal", min_score=70)) == "Principal"


# --------------------------------------------------------------- desempates
def test_priority_wins() -> None:
    generic = Channel("Todo", priority=10)
    specific = Channel("Speed Clips", people=["speed"], priority=1)

    assert chosen(clip(), generic, specific) == "Todo"


def test_at_equal_priority_the_pickiest_wins() -> None:
    """Un canal específico debe ganarle a uno genérico."""
    generic = Channel("Todo")
    specific = Channel("Speed Clips", people=["speed"], kinds=["reaccion"])

    assert chosen(clip(), generic, specific) == "Speed Clips"


def test_the_result_does_not_depend_on_the_order() -> None:
    a = Channel("Alfa", people=["speed"])
    b = Channel("Beta", people=["speed"])

    assert chosen(clip(), a, b) == chosen(clip(), b, a)


# ------------------------------------------------------------------ apagado
def test_a_paused_channel_receives_nothing() -> None:
    assert chosen(clip(), Channel("Speed Clips", people=["speed"], enabled=False)) is None


def test_with_no_channels_nothing_is_routed() -> None:
    assert route(clip(), []) is None


# ------------------------------------------------------------ sin etiquetar
def test_a_clip_without_tags_only_fits_a_catch_all() -> None:
    """Sin etiquetas no se puede afirmar que encaje en una línea editorial."""
    bare = ClipFacts.from_tags(None, score=80.0)

    assert chosen(bare, Channel("Speed Clips", people=["speed"])) is None
    assert chosen(bare, Channel("Todo")) == "Todo"


def test_the_tags_of_the_tagger_are_read_as_they_were_saved() -> None:
    facts = ClipFacts.from_tags(
        {"niche": "streamers", "people": ["speed"], "topics": [], "kind": "fail"},
        score=60.0,
    )

    assert facts.people == ("speed",)
    assert facts.kind == "fail"


# --------------------------------------------------------------- en conjunto
def test_several_clips_are_split_between_channels() -> None:
    channels = [
        Channel("Speed Clips", people=["speed"]),
        Channel("Kai Clips", people=["kai cenat"]),
    ]
    clips = [
        ("a", clip(people=("speed",))),
        ("b", clip(people=("kai cenat",))),
        ("c", clip(people=("poki",))),
    ]

    routed = route_all(clips, channels)

    assert routed["a"].channel.name == "Speed Clips"
    assert routed["b"].channel.name == "Kai Clips"
    # El tercero no encaja en ninguno y no aparece: lo reparte una persona.
    assert "c" not in routed
