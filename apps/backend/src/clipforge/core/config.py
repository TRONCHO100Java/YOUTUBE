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
# "auto" decide por proyecto a partir de cuánta habla real trae la transcripción.
ContentProfileSetting = Literal["auto", "talking", "visual"]
WhisperTask = Literal["transcribe", "translate"]


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
    # Vista derivada de los clips con nombres legibles, para subirlos a mano.
    # Se puede apuntar a una carpeta sincronizada con la nube.
    export_path: Path | None = None
    export_clips: bool = True

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

    # ------------------------------------------------------------- encuadre
    #: Coloca la ventana vertical sobre el sujeto en lugar de centrarla. En un
    #: plano general con dos personas, centrar deja a una fuera del clip.
    smart_crop: bool = True
    #: Ancho al que se analizan los fotogramas para detectar caras.
    smart_crop_analysis_width: int = 480
    #: Fotogramas por segundo que se muestrean de cada clip.
    smart_crop_sample_fps: float = 2.0
    #: Tope de muestras por clip, para que un clip largo no dispare el coste.
    smart_crop_max_samples: int = 90
    #: Ventana de la media móvil que suaviza el seguimiento.
    smart_crop_smoothing: int = 5
    #: Paneo. Desactivado por defecto: un seguimiento con temblor marea más de
    #: lo que aporta, y una ventana fija bien colocada ya arregla el problema.
    smart_crop_pan: bool = False
    #: Fracción del ancho de la ventana que el sujeto debe recorrer para que
    #: valga la pena panear en lugar de dejarla fija.
    smart_crop_pan_ratio: float = 0.6
    #: Tope de tramos de la expresión de paneo: se evalúa en cada fotograma.
    smart_crop_max_keyframes: int = 12

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
    # "translate" devuelve el texto en inglés sea cual sea el idioma original.
    # Sobre un vídeo en bengalí o hindi es la diferencia entre que el LLM pueda
    # razonar sobre lo que se dice y que reciba caracteres que no entiende.
    whisper_task: WhisperTask = "transcribe"
    # Sin esto, Whisper arrastra el texto anterior como contexto y entra en
    # bucles de alucinación sobre música o ruido ("롱 롱 롱 롱").
    whisper_condition_on_previous_text: bool = False

    # ------------------------------------------------------------------- ia
    ai_provider: AIProvider = "ollama"
    ai_model: str = "qwen2.5:14b"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ai_max_retries: int = 3
    ai_request_timeout_seconds: int = 120
    # Modelo con visión, para los vídeos que no se pueden juzgar por su texto.
    # Vacío = mismo proveedor que `ai_provider`.
    ai_vision_provider: AIProvider | None = None
    ai_vision_model: str = "qwen2.5vl:7b"
    ai_vision_enabled: bool = True
    #: Fotogramas que se le enseñan al modelo por cada bloque candidato.
    vision_frames_per_block: int = 5
    #: Tope de bloques que se envían a analizar, del mejor puntuado hacia abajo.
    vision_max_blocks: int = 15
    #: Bloques por petición. Uno, a propósito: con tres en el mismo mensaje, un
    #: modelo local de 7B deja de distinguirlos y devuelve el mismo título y la
    #: misma nota para los tres. Con uno solo describe la escena concreta.
    #: Súbelo solo si usas un modelo grande, donde agrupar sale más barato.
    vision_blocks_per_request: int = 1

    # ------------------------------------------------------- perfil de contenido
    content_profile: ContentProfileSetting = "auto"
    #: Por debajo de esta fracción de habla, el vídeo se trata como visual.
    visual_speech_ratio: float = 0.25
    #: Segundo criterio: densidad de texto. Una transcripción de tres palabras
    #: puede tener un ratio alto si el vídeo es muy corto.
    visual_chars_per_minute: float = 200.0
    #: Por debajo de esto la transcripción se considera alucinada y se descarta
    #: en lugar de pasársela al analizador.
    min_usable_speech_ratio: float = 0.02

    # ---------------------------------------------------------------- clips
    max_clips_per_project: int = 5
    min_clip_duration: int = 20
    max_clip_duration: int = 90
    target_clip_duration: int = 45
    # Duraciones del perfil visual: un gag se agota antes que una explicación.
    visual_min_clip_duration: int = 10
    visual_max_clip_duration: int = 60
    visual_target_clip_duration: int = 25
    #: Escribe el gancho del clip arriba, en los primeros segundos. Es lo
    #: único escrito que lleva un clip sin diálogo, y donde se decide si
    #: alguien sigue mirando.
    hook_overlay: bool = True
    hook_overlay_seconds: float = 3.0
    #: 100 px sobre 1920 son algo más del 5 % de la altura, que es donde
    #: está el texto de gancho en los Shorts que funcionan. A 78 se leía,
    #: pero no frenaba el scroll.
    hook_font_size: int = 100
    #: Caracteres por línea del gancho antes de partir.
    hook_line_length: int = 22
    analysis_chunk_seconds: int = 300
    analysis_chunk_overlap_seconds: int = 60
    burn_subtitles: bool = True

    # -------------------------------------------------------------- señales
    #: Las señales alimentan el análisis visual Y la línea de tiempo del
    #: editor manual, así que se miden en todos los proyectos. Sobre un
    #: vídeo de nueve minutos cuestan unos diecisiete segundos.
    signals_enabled: bool = True
    #: Resolución temporal de la curva de energía, en segundos.
    signal_energy_interval_seconds: float = 0.5
    #: Umbral de `select='gt(scene,N)'`. Más bajo detecta más cortes y más
    #: falsos positivos; 0,35 funciona bien en material de YouTube.
    signal_scene_threshold: float = 0.35
    #: Separación mínima entre picos de volumen: colapsa las ráfagas.
    signal_peak_min_gap_seconds: float = 8.0
    #: La curva de movimiento cuesta como la de cortes. Desactívala si el
    #: worker va justo de CPU.
    signal_measure_motion: bool = True

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

    @field_validator("storage_path", "export_path", mode="after")
    @classmethod
    def _anchor_to_repo(cls, value: Path | None) -> Path | None:
        """Ancla las rutas relativas del .env a la raiz del repositorio.

        El backend se arranca desde directorios distintos (uvicorn desde
        apps/backend, celery, pytest, alembic), asi que resolver contra el cwd
        haria que "./storage" apuntase a un sitio diferente en cada proceso.
        """
        if value is None or value.is_absolute():
            return value
        return (REPO_ROOT / value).resolve()

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
    def export_dir(self) -> Path:
        """Carpeta de exportacion. Sin EXPORT_PATH, cuelga del storage."""
        return self.export_path or self.storage_path / "export"

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
