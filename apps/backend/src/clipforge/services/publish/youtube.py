"""Subida de clips a YouTube.

Es el último tramo manual del flujo: hasta aquí el sistema deja cinco MP4 y su
texto listos, y luego había que abrir la carpeta y subirlos uno a uno pegando
título, descripción y etiquetas a mano.

**Un muro que conviene conocer antes de usar esto.** La API de datos de YouTube
restringe a *privado* todo lo que sube un proyecto de Google Cloud que no ha
pasado su auditoría de cumplimiento. La subida funciona igual —el vídeo queda
en el canal, con su título y su descripción— pero hay que entrar a publicarlo.
Por eso `YOUTUBE_PRIVACY` viene en `private` de fábrica: es lo que va a pasar de
todos modos, y prometer otra cosa sería mentir. Con la auditoría aprobada se
cambia a `public` y ya está.

Aun con esa limitación el trabajo que ahorra es real: el fichero, el título, la
descripción con su crédito y las etiquetas suben solos y colocados.

Credenciales: se necesita un `client_secrets.json` de un proyecto de Google
Cloud con la API de YouTube activada. La primera vez hay que autorizar en el
navegador **una sola vez**; a partir de ahí se guarda un token que se refresca
solo. Eso no lo puede hacer el servidor por su cuenta, así que vive en un
comando aparte (`python -m clipforge.services.publish.authorize`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError, ExternalToolError
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

#: Permiso mínimo para subir. `youtube.upload` no deja leer nada del canal, que
#: es justo lo que queremos: este código sube, no husmea.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

#: Privacidad admitida por la API.
PRIVACY_VALUES = ("private", "unlisted", "public")

#: Categoría 24 = Entertainment. Es la que corresponde a clips de streams y
#: comedia; cambiarla por vídeo no aporta nada al alcance.
CATEGORY_ID = "24"

#: Tope de YouTube para el título. Se corta antes de enviarlo: que la API
#: rechace una subida entera por dos caracteres sería absurdo.
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
#: Etiquetas: el límite real es de 500 caracteres en total.
MAX_TAGS_CHARS = 480

#: Trozo de subida. 4 MB va bien en una conexión doméstica: reintentar un
#: trozo perdido cuesta poco y el progreso se ve avanzar.
CHUNK_SIZE = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadRequest:
    """Un clip listo para subir, con su texto ya compuesto."""

    video: Path
    title: str
    description: str
    tags: tuple[str, ...] = ()
    privacy: str = "private"


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Lo que YouTube devuelve de una subida."""

    video_id: str
    url: str
    privacy: str


def is_configured() -> bool:
    """¿Hay credenciales para subir?

    Se comprueba antes de ofrecer el botón: pedirle a alguien que pulse algo
    que no puede funcionar es peor que no ofrecerlo.
    """
    token = settings.youtube_token_file
    return token is not None and Path(token).is_file()


def upload_clip(request: UploadRequest) -> UploadResult:
    """Sube un clip y devuelve su id y su URL.

    Raises:
        ClipForgeError: si falta el fichero o las credenciales.
        ExternalToolError: si YouTube rechaza la subida.
    """
    if not request.video.is_file():
        raise ClipForgeError(f"El clip no está en disco: {request.video}")

    credentials = _load_credentials()
    body = _body(request)

    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover - depende de la instalación
        raise ClipForgeError(
            "Faltan las librerías de Google. Instálalas con: pip install -e .[publish]"
        ) from exc

    media = MediaFileUpload(
        str(request.video), chunksize=CHUNK_SIZE, resumable=True, mimetype="video/mp4"
    )
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)

    try:
        call = service.videos().insert(part="snippet,status", body=body, media_body=media)
        response = _run(call)
    except HttpError as exc:
        raise ExternalToolError(
            "YouTube ha rechazado la subida", details={"error": str(exc)[:500]}
        ) from exc

    video_id = str(response.get("id") or "")
    if not video_id:
        raise ExternalToolError("YouTube no ha devuelto el id del vídeo subido")

    privacy = str((response.get("status") or {}).get("privacyStatus") or request.privacy)
    logger.info("publish.uploaded", video_id=video_id, privacy=privacy)

    return UploadResult(
        video_id=video_id,
        url=f"https://www.youtube.com/shorts/{video_id}",
        privacy=privacy,
    )


# ------------------------------------------------------------------- privado
def _run(call: Any) -> dict[str, Any]:
    """Ejecuta una subida reanudable hasta que termina.

    Trozo a trozo y no de una vez: una subida de 30 MB que se corta al 90 % no
    debe empezar de cero, y así además se puede registrar el avance.
    """
    response = None
    while response is None:
        _, response = call.next_chunk()
    return dict(response)


def _body(request: UploadRequest) -> dict[str, Any]:
    """Metadatos del vídeo, recortados a lo que YouTube admite."""
    privacy = request.privacy if request.privacy in PRIVACY_VALUES else "private"

    return {
        "snippet": {
            "title": request.title[:MAX_TITLE],
            "description": request.description[:MAX_DESCRIPTION],
            "tags": list(_fit_tags(request.tags)),
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": privacy,
            # Nada de esto es para niños, y dejarlo sin declarar hace que
            # YouTube pregunte por cada vídeo desde el panel.
            "selfDeclaredMadeForKids": False,
        },
    }


def _fit_tags(tags: tuple[str, ...]) -> list[str]:
    """Etiquetas que caben en el límite total de caracteres de YouTube.

    Se cortan por el final: las primeras son las que más describen el clip
    —`shorts` y los nombres propios—, así que son las que deben sobrevivir.
    """
    fitted: list[str] = []
    used = 0
    for tag in tags:
        # Cada etiqueta cuenta su longitud más la coma que la separa.
        cost = len(tag) + 1
        if used + cost > MAX_TAGS_CHARS:
            break
        fitted.append(tag)
        used += cost
    return fitted


def _load_credentials() -> Any:
    """Credenciales guardadas, refrescándolas si han caducado.

    Raises:
        ClipForgeError: si no hay token o ya no sirve.
    """
    token_file = settings.youtube_token_file
    if not token_file or not Path(token_file).is_file():
        raise ClipForgeError(
            "No hay autorización de YouTube. Ejecuta una vez: "
            "python -m clipforge.services.publish.authorize"
        )

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - depende de la instalación
        raise ClipForgeError(
            "Faltan las librerías de Google. Instálalas con: pip install -e .[publish]"
        ) from exc

    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not credentials.valid:
        if not (credentials.expired and credentials.refresh_token):
            raise ClipForgeError(
                "La autorización de YouTube ya no sirve. Vuelve a ejecutar: "
                "python -m clipforge.services.publish.authorize"
            )
        credentials.refresh(Request())
        # El token refrescado se guarda: si no, se pide uno nuevo en cada
        # subida y se gasta cuota de autenticación para nada.
        Path(token_file).write_text(credentials.to_json(), encoding="utf-8")

    return credentials
