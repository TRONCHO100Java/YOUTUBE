"""Selección del codificador de vídeo.

`VIDEO_ENCODER=auto` usa NVENC si la GPU puede, y cae a libx264 si no. La
comprobación es una codificación real de prueba, no una lectura de la lista de
codificadores: ffmpeg puede traer `h264_nvenc` compilado y aun así fallar al
usarlo (driver antiguo, GPU sin NVENC, sesiones agotadas).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

NVENC = "h264_nvenc"
LIBX264 = "libx264"

PROBE_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class EncoderProfile:
    """Codificador elegido y los argumentos de ffmpeg que lo configuran."""

    name: str
    args: list[str]

    @property
    def uses_gpu(self) -> bool:
        return self.name == NVENC


def resolve_encoder() -> EncoderProfile:
    """Devuelve el codificador a usar según la configuración y el hardware.

    Raises:
        ExternalToolError: si se pide NVENC explícitamente y no funciona. No se
            cae a CPU en silencio: el usuario ha pedido GPU y debe enterarse de
            que no la está usando.
    """
    configured = settings.video_encoder

    if configured == LIBX264:
        return _profile(LIBX264)

    if configured == NVENC:
        if not nvenc_is_usable():
            raise ExternalToolError(
                "VIDEO_ENCODER=h264_nvenc pero NVENC no funciona en esta máquina. "
                "Revisa los drivers NVIDIA o usa VIDEO_ENCODER=auto."
            )
        return _profile(NVENC)

    # auto
    if nvenc_is_usable():
        return _profile(NVENC)
    logger.warning("encoder.falling_back_to_cpu", reason="NVENC no disponible")
    return _profile(LIBX264)


@lru_cache(maxsize=1)
def nvenc_is_usable() -> bool:
    """Codifica dos fotogramas de prueba con NVENC para saber si sirve.

    Se cachea: la comprobación cuesta cerca de un segundo y el resultado no
    cambia mientras viva el proceso.
    """
    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=black:size=256x256:rate=2:duration=1",
        "-c:v",
        NVENC,
        "-frames:v",
        "2",
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("encoder.nvenc_probe_failed", error=str(exc))
        return False

    usable = completed.returncode == 0
    logger.info("encoder.nvenc_probe", usable=usable)
    return usable


def _profile(name: str) -> EncoderProfile:
    if name == NVENC:
        bitrate = settings.video_bitrate
        return EncoderProfile(
            name=NVENC,
            args=[
                "-c:v",
                NVENC,
                # p5 + hq: buen equilibrio calidad/velocidad en Ada y Blackwell.
                "-preset",
                "p5",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-b:v",
                bitrate,
                "-maxrate",
                bitrate,
                "-bufsize",
                _double(bitrate),
                # Sin esto, algunos reproductores móviles no aceptan el fichero.
                "-pix_fmt",
                "yuv420p",
            ],
        )

    return EncoderProfile(
        name=LIBX264,
        args=[
            "-c:v",
            LIBX264,
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ],
    )


def _double(bitrate: str) -> str:
    """Duplica un bitrate del estilo '8M' o '6000k' para el buffer."""
    value = bitrate.strip()
    suffix = value[-1] if value and value[-1].isalpha() else ""
    number = value[: -1 if suffix else None]
    try:
        return f"{int(float(number) * 2)}{suffix}"
    except ValueError:
        return value
