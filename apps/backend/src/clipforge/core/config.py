"""Configuracion central de la aplicacion (12-factor: todo por entorno)."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from clipforge.core.paths import REPO_ROOT

# Sin "mock": la aplicación no lleva simulaciones. El analizador de prueba
# vive en los tests, que es donde tiene sentido.
AIProvider = Literal["ollama", "openai", "anthropic"]
LogFormat = Literal["console", "json"]


class Settings(BaseSettings):
    """Configuracion tipada. Se lee de variables de entorno y del .env de la raiz."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    app_name: str = "ClipForge"
    environment: Literal["local", "staging", "production"] = "local"
    debug: bool = True
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    # ------------------------------------------------------------ persistencia
    # URL canonica sin driver: derivamos el sync (psycopg) y el async (asyncpg).
    database_url: str = "postgresql://clipforge:clipforge@localhost:5442/clipforge"
    db_echo: bool = False
    redis_url: str = "redis://localhost:6390/0"

    # ------------------------------------------------------------------- api
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # NoDecode: evita que pydantic-settings intente json.loads() sobre el valor del
    # .env; asi nuestro validador puede aceptar tambien formato CSV.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --------------------------------------------------------------- storage
    storage_path: Path = REPO_ROOT / "storage"
    # Conservar el original por defecto: el render de clips lo necesita y
    # volver a descargarlo es lento y puede fallar (vídeo retirado, límites
    # de YouTube). En local el disco sale más barato que el ancho de banda.
    keep_source_video: bool = True
    keep_audio: bool = False
    keep_temp_files: bool = False

    # ---------------------------------------------------------------- fuentes
    allowed_source_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
        ]
    )
    max_source_duration_seconds: int = 4 * 60 * 60
    max_source_filesize_mb: int = 4096

    # ------------------------------------------------------------- multimedia
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    # Se prioriza H.264 + AAC: son los códecs que mejor se cortan y re-codifican
    # con NVENC. Sin esto YouTube sirve AV1 + Opus, que complica el render.
    ytdlp_format: str = (
        "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]"
        "/bestvideo[height<=1080]+bestaudio"
        "/best[height<=1080]/best"
    )
    video_encoder: Literal["auto", "h264_nvenc", "libx264"] = "auto"
    video_bitrate: str = "8M"
    output_width: int = 1080
    output_height: int = 1920

    # ------------------------------------------------------------- whisper
    whisper_model: str = "large-v3"
    whisper_device: Literal["cuda", "cpu", "auto"] = "cuda"
    whisper_compute_type: str = "float16"
    whisper_beam_size: int = 5
    whisper_language: str | None = None
    whisper_word_timestamps: bool = True
    # El VAD descarta silencios y música: acelera la transcripción y evita
    # que el modelo alucine texto en los tramos sin voz.
    whisper_vad_filter: bool = True

    # ------------------------------------------------------------------- ia
    ai_provider: AIProvider = "ollama"
    ai_model: str = "qwen2.5:14b"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ai_max_retries: int = 3
    ai_request_timeout_seconds: int = 120

    # ---------------------------------------------------------------- clips
    max_clips_per_project: int = 5
    min_clip_duration: int = 20
    max_clip_duration: int = 90
    target_clip_duration: int = 45
    analysis_chunk_seconds: int = 300
    analysis_chunk_overlap_seconds: int = 60
    burn_subtitles: bool = True

    # --------------------------------------------------------------- worker
    celery_task_time_limit: int = 3 * 60 * 60
    celery_task_soft_time_limit: int = 3 * 60 * 60 - 300
    celery_worker_concurrency: int = 1

    # ------------------------------------------------------------ validadores
    @field_validator("cors_origins", "allowed_source_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Permite definir listas como CSV en el .env (mas comodo que JSON)."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _strip_driver(cls, value: str) -> str:
        """Normaliza a `postgresql://` para poder derivar cualquier driver."""
        if "+" in value.split("://", 1)[0]:
            scheme, rest = value.split("://", 1)
            return f"{scheme.split('+', 1)[0]}://{rest}"
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """URL para Alembic y para el worker Celery (codigo sincrono)."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """URL para FastAPI (codigo asincrono)."""
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton cacheado: evita releer el .env en cada request/tarea."""
    return Settings()


settings = get_settings()
