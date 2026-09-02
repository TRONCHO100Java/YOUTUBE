"""Resolución de dispositivo y tipo de cómputo de Whisper.

Es la lógica que decide si se usa la GPU, y la que debe fallar de forma ruidosa
cuando se pide CUDA y no la hay: una caída silenciosa a CPU con large-v3 haría
que una transcripción de 10 minutos tardase horas sin que nadie se entere.
"""

from __future__ import annotations

import ctranslate2
import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.transcribe.whisper import resolve_compute_type, resolve_device


@pytest.fixture
def no_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)


@pytest.fixture
def with_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)


def test_cpu_is_respected_without_probing_the_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "cpu")
    assert resolve_device() == "cpu"


@pytest.mark.usefixtures("with_cuda")
def test_uses_cuda_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "cuda")
    assert resolve_device() == "cuda"


@pytest.mark.usefixtures("no_cuda")
def test_explicit_cuda_without_gpu_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "cuda")
    with pytest.raises(ExternalToolError, match="GPU"):
        resolve_device()


@pytest.mark.usefixtures("no_cuda")
def test_auto_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "auto")
    assert resolve_device() == "cpu"


@pytest.mark.usefixtures("with_cuda")
def test_auto_prefers_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "auto")
    assert resolve_device() == "cuda"


def test_broken_cuda_probe_is_treated_as_no_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> int:
        raise RuntimeError("driver roto")

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", explode)
    monkeypatch.setattr(settings, "whisper_device", "auto")
    assert resolve_device() == "cpu"


@pytest.mark.parametrize("requested", ["float16", "int8_float16"])
def test_float16_is_downgraded_on_cpu(monkeypatch: pytest.MonkeyPatch, requested: str) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", requested)
    assert resolve_compute_type("cpu") == "int8"


def test_compute_type_is_untouched_on_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", "float16")
    assert resolve_compute_type("cuda") == "float16"


def test_int8_is_valid_on_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", "int8")
    assert resolve_compute_type("cpu") == "int8"
