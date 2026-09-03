"""Selección del codificador y comprobación real de NVENC."""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.video.encoder import (
    LIBX264,
    NVENC,
    _double,
    nvenc_is_usable,
    resolve_encoder,
)


@pytest.fixture(autouse=True)
def clear_probe_cache() -> None:
    """El resultado de la comprobación se cachea; los tests parten de cero."""
    nvenc_is_usable.cache_clear()


def test_libx264_is_used_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "video_encoder", LIBX264)
    profile = resolve_encoder()

    assert profile.name == LIBX264
    assert profile.uses_gpu is False
    assert "-c:v" in profile.args


def test_auto_falls_back_to_cpu_without_nvenc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "video_encoder", "auto")
    monkeypatch.setattr("clipforge.services.video.encoder.nvenc_is_usable", lambda: False)

    assert resolve_encoder().name == LIBX264


def test_auto_prefers_nvenc_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "video_encoder", "auto")
    monkeypatch.setattr("clipforge.services.video.encoder.nvenc_is_usable", lambda: True)

    profile = resolve_encoder()
    assert profile.name == NVENC
    assert profile.uses_gpu is True


def test_explicit_nvenc_without_gpu_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pedir GPU y renderizar en CPU en silencio sería una sorpresa cara."""
    monkeypatch.setattr(settings, "video_encoder", NVENC)
    monkeypatch.setattr("clipforge.services.video.encoder.nvenc_is_usable", lambda: False)

    with pytest.raises(ExternalToolError, match="NVENC"):
        resolve_encoder()


def test_nvenc_probe_actually_encodes() -> None:
    """Comprobación real: ffmpeg puede traer NVENC compilado y aun así fallar."""
    assert nvenc_is_usable() is True, "esta máquina tiene una RTX 5080; NVENC debe funcionar"


def test_nvenc_probe_is_cached() -> None:
    nvenc_is_usable()
    nvenc_is_usable()
    assert nvenc_is_usable.cache_info().hits >= 1


@pytest.mark.parametrize(
    ("bitrate", "expected"),
    [("8M", "16M"), ("6000k", "12000k"), ("4M", "8M"), ("500", "1000")],
)
def test_buffer_size_doubles_the_bitrate(bitrate: str, expected: str) -> None:
    assert _double(bitrate) == expected


def test_unparseable_bitrate_is_passed_through() -> None:
    assert _double("no-es-un-bitrate") == "no-es-un-bitrate"
