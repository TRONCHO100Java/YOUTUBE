"""Transcripción con faster-whisper sobre CUDA.

El modelo se carga una vez por proceso y se reutiliza entre tareas: cargar
large-v3 en la GPU cuesta varios segundos y hacerlo en cada clip sería absurdo.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from clipforge.core.config import settings
from clipforge.core.cuda import ensure_cuda_libraries
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.transcribe.base import (
    Segment,
    Transcriber,
    TranscriptionResult,
    Word,
)

logger = get_logger(__name__)

#: Cache de modelos por (nombre, dispositivo, tipo de cómputo).
_models: dict[tuple[str, str, str], Any] = {}
_models_lock = threading.Lock()


def resolve_device() -> str:
    """Decide el dispositivo real a partir de `WHISPER_DEVICE`.

    Raises:
        ExternalToolError: si se pide CUDA explícitamente y no hay GPU utilizable.
            No caemos a CPU en silencio: large-v3 en CPU tarda órdenes de
            magnitud más y el usuario debe enterarse.
    """
    configured = settings.whisper_device
    if configured == "cpu":
        return "cpu"

    ensure_cuda_libraries()
    try:
        import ctranslate2

        available = ctranslate2.get_cuda_device_count() > 0
    except Exception as exc:
        logger.warning("whisper.cuda_probe_failed", error=str(exc))
        available = False

    if available:
        return "cuda"
    if configured == "cuda":
        raise ExternalToolError(
            "WHISPER_DEVICE=cuda pero no se detecta ninguna GPU utilizable. "
            "Revisa los drivers NVIDIA o cambia a WHISPER_DEVICE=cpu."
        )

    logger.warning("whisper.falling_back_to_cpu")
    return "cpu"


def resolve_compute_type(device: str) -> str:
    """float16 no existe en CPU: se degrada a int8, que sí es utilizable."""
    compute_type = settings.whisper_compute_type
    if device == "cpu" and compute_type in ("float16", "int8_float16"):
        logger.warning("whisper.compute_type_downgraded", requested=compute_type, using="int8")
        return "int8"
    return compute_type


class FasterWhisperTranscriber(Transcriber):
    """Implementación de `Transcriber` sobre faster-whisper (ctranslate2)."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ) -> None:
        self.model_name = model_name or settings.whisper_model
        self.device = device or resolve_device()
        self.compute_type = compute_type or resolve_compute_type(self.device)

    # ------------------------------------------------------------------ modelo
    def _load_model(self) -> Any:
        key = (self.model_name, self.device, self.compute_type)
        with _models_lock:
            model = _models.get(key)
            if model is not None:
                return model

            ensure_cuda_libraries()
            from faster_whisper import WhisperModel

            logger.info(
                "whisper.loading_model",
                model=self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            started = time.perf_counter()
            try:
                model = WhisperModel(
                    self.model_name, device=self.device, compute_type=self.compute_type
                )
            except Exception as exc:
                raise ExternalToolError(
                    f"No se ha podido cargar el modelo Whisper '{self.model_name}' "
                    f"en {self.device}: {exc}"
                ) from exc

            _models[key] = model
            logger.info("whisper.model_ready", seconds=round(time.perf_counter() - started, 1))
            return model

    # ------------------------------------------------------------ transcripción
    def transcribe(
        self, audio_path: Path, *, language: str | None = None, task: str | None = None
    ) -> TranscriptionResult:
        if not audio_path.is_file():
            raise ExternalToolError(f"No existe el audio a transcribir: {audio_path}")

        model = self._load_model()
        started = time.perf_counter()

        try:
            raw_segments, info = model.transcribe(
                str(audio_path),
                language=language or settings.whisper_language,
                # "translate" devuelve inglés sea cual sea el idioma original.
                # Sobre un vídeo en bengalí o hindi es la diferencia entre que
                # el LLM razone sobre lo que se dice y que reciba caracteres
                # que no sabe leer.
                task=task or settings.whisper_task,
                beam_size=settings.whisper_beam_size,
                word_timestamps=settings.whisper_word_timestamps,
                # El VAD descarta silencios y música: acelera mucho y evita que
                # el modelo alucine texto en los tramos sin voz.
                vad_filter=settings.whisper_vad_filter,
                # Sin esto Whisper arrastra su propia salida como contexto y
                # entra en bucle sobre música o ruido, repitiendo la misma
                # sílaba durante minutos.
                condition_on_previous_text=settings.whisper_condition_on_previous_text,
            )
            # faster-whisper devuelve un generador perezoso: la transcripción
            # real ocurre al consumirlo.
            segments = [_to_segment(index, raw) for index, raw in enumerate(raw_segments)]
        except ExternalToolError:
            raise
        except Exception as exc:
            raise ExternalToolError(f"Whisper ha fallado al transcribir: {exc}") from exc

        elapsed = time.perf_counter() - started
        duration = float(getattr(info, "duration", 0.0)) or None
        logger.info(
            "whisper.transcribed",
            segments=len(segments),
            language=info.language,
            audio_seconds=round(duration or 0, 1),
            seconds=round(elapsed, 1),
            speed=f"{(duration or 0) / elapsed:.1f}x" if elapsed > 0 else None,
        )

        return TranscriptionResult(
            language=info.language,
            language_probability=float(info.language_probability)
            if info.language_probability is not None
            else None,
            duration=duration,
            model_name=self.model_name,
            segments=segments,
        )


def _to_segment(index: int, raw: Any) -> Segment:
    words = [
        Word(
            word=word.word,
            start=float(word.start),
            end=float(word.end),
            probability=float(word.probability) if word.probability is not None else None,
        )
        for word in (raw.words or [])
    ]
    return Segment(
        index=index,
        start=float(raw.start),
        end=float(raw.end),
        text=raw.text.strip(),
        words=words,
    )
