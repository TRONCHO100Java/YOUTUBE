"""Encontrar vídeos sin salir de la aplicación.

Hasta ahora el sistema esperaba a que alguien pegase una URL. Este módulo es la
otra mitad: buscar en YouTube y vigilar canales, para que los vídeos entren
solos en la cola.

**No usa la API de datos de YouTube.** Ni clave, ni proyecto en Google Cloud, ni
cuota que se agota a las cien búsquedas. Las dos cosas que hacen falta ya están
disponibles gratis:

- **Buscar**: `yt-dlp` con `ytsearchN:`. Ya es una dependencia del proyecto —es
  lo que descarga los vídeos— y en extracción plana devuelve título, duración,
  vistas y canal en algo más de un segundo, sin bajar un solo byte de vídeo.
- **Vigilar un canal**: cada canal de YouTube publica un RSS con sus últimos
  quince vídeos. Es un GET de 0,3 segundos sin autenticación.

Filtrar **antes** de descargar es el objetivo de todo esto: bajar 400 MB para
descubrir que el vídeo duraba tres horas o tenía doscientas visitas es el gasto
más tonto del pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from xml.etree import ElementTree

import httpx
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from clipforge.core.errors import ExternalToolError, ValidationError
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

#: RSS de un canal. Es una URL pública y estable de YouTube; no hay que
#: autenticarse ni pedir cuota, y trae los quince últimos vídeos.
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

#: Espacios de nombres del Atom que devuelve YouTube.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

#: Los ids de canal son "UC" + 22 caracteres base64url.
_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")

#: Tope de resultados por búsqueda. Más no ayuda a decidir y multiplica la
#: espera: yt-dlp resuelve cada resultado aunque sea en extracción plana.
MAX_SEARCH_RESULTS = 30

#: Una búsqueda no debería tardar más que esto. Si tarda, algo va mal en la red
#: y es mejor decirlo que dejar la interfaz girando.
SEARCH_TIMEOUT_SECONDS = 60

#: Opciones comunes: nada de descarga, nada de ruido en el log y extracción
#: plana, que es la que devuelve la lista sin resolver cada vídeo entero.
_FLAT_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
    "socket_timeout": SEARCH_TIMEOUT_SECONDS,
}


@dataclass(frozen=True, slots=True)
class VideoResult:
    """Un vídeo encontrado, con lo justo para decidir si merece descargarse."""

    video_id: str
    title: str
    url: str
    channel: str | None = None
    channel_id: str | None = None
    duration: float | None = None
    view_count: int | None = None
    thumbnail: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChannelRef:
    """Un canal resuelto a su id, que es lo único con lo que se puede trabajar.

    La gente copia `@handle`, `/c/nombre` o la URL de un vídeo del canal; el
    RSS solo entiende el id `UC...`.
    """

    channel_id: str
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class DiscoveryFilters:
    """Qué vídeos merecen entrar en la cola.

    Se aplican **antes** de descargar. Un vídeo de tres horas o uno con
    doscientas visitas cuesta lo mismo de bajar que uno bueno.
    """

    min_duration: int | None = None
    max_duration: int | None = None
    min_views: int | None = None

    def accepts(self, video: VideoResult) -> bool:
        """¿Pasa el filtro?

        Un dato que falta no descarta: YouTube no siempre da las vistas en
        extracción plana, y tirar un vídeo por lo que no sabemos de él es peor
        que dejarlo pasar y decidir luego.
        """
        duration = video.duration
        if duration is not None:
            if self.min_duration is not None and duration < self.min_duration:
                return False
            if self.max_duration is not None and duration > self.max_duration:
                return False

        views = video.view_count
        return not (views is not None and self.min_views is not None and views < self.min_views)


# -------------------------------------------------------------------- buscar
def search_videos(
    query: str, *, limit: int = 12, filters: DiscoveryFilters | None = None
) -> list[VideoResult]:
    """Busca en YouTube y devuelve los resultados que pasan el filtro.

    Raises:
        ValidationError: si la consulta está vacía.
        ExternalToolError: si yt-dlp no puede completar la búsqueda.
    """
    term = (query or "").strip()
    if not term:
        raise ValidationError("Escribe algo que buscar")

    count = max(1, min(limit, MAX_SEARCH_RESULTS))
    try:
        # Los tipos de yt-dlp declaran un TypedDict cerrado de opciones;
        # construirlas como diccionario obliga a este cast, igual que en el
        # descargador.
        with YoutubeDL(cast(Any, _FLAT_OPTIONS)) as ydl:
            # `ytsearchN:` es la sintaxis de búsqueda de yt-dlp. El término va
            # dentro de la URL falsa, así que no puede escaparse a la línea de
            # comandos: aquí no hay shell.
            info = ydl.extract_info(f"ytsearch{count}:{term}", download=False)
    except DownloadError as exc:
        raise ExternalToolError(
            "No se ha podido buscar en YouTube", details={"error": str(exc)[:300]}
        ) from exc

    entries = cast(list[Any], (info or {}).get("entries") or [])
    rules = filters or DiscoveryFilters()
    results = [video for video in (_video_from_entry(entry) for entry in entries) if video]
    accepted = [video for video in results if rules.accepts(video)]

    logger.info("discover.searched", query=term, found=len(results), accepted=len(accepted))
    return accepted


# ------------------------------------------------------------------- canales
def resolve_channel(raw: str) -> ChannelRef:
    """Resuelve lo que sea que haya pegado el usuario a un canal con id.

    Vale un `@handle`, la URL del canal o la de cualquiera de sus vídeos: de
    todas ellas yt-dlp saca el `channel_id`, que es lo único que entiende el
    RSS.

    Raises:
        ValidationError: si no hay nada que resolver.
        ExternalToolError: si YouTube no reconoce el canal.
    """
    text = (raw or "").strip()
    if not text:
        raise ValidationError("Indica un canal")

    if _CHANNEL_ID.match(text):
        url = f"https://www.youtube.com/channel/{text}"
    elif text.startswith("@"):
        url = f"https://www.youtube.com/{text}"
    elif "youtube.com" in text or "youtu.be" in text:
        url = text if "://" in text else f"https://{text}"
    else:
        url = f"https://www.youtube.com/@{text}"

    try:
        with YoutubeDL(cast(Any, {**_FLAT_OPTIONS, "playlistend": 1})) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except DownloadError as exc:
        raise ExternalToolError(
            f"YouTube no reconoce el canal '{text}'", details={"error": str(exc)[:300]}
        ) from exc

    channel_id = info.get("channel_id") or info.get("uploader_id")
    if not channel_id or not _CHANNEL_ID.match(str(channel_id)):
        raise ExternalToolError(f"No se ha podido identificar el canal de '{text}'")

    title = info.get("channel") or info.get("uploader") or str(channel_id)
    return ChannelRef(
        channel_id=str(channel_id),
        title=str(title),
        url=f"https://www.youtube.com/channel/{channel_id}",
    )


def channel_feed(channel_id: str, *, timeout: float = 20.0) -> list[VideoResult]:
    """Los últimos vídeos de un canal, leídos de su RSS.

    Es un GET sin autenticación y sin cuota, así que se puede repetir cada
    pocos minutos sin gastar nada.

    Raises:
        ValidationError: si el id no tiene forma de id de canal.
        ExternalToolError: si el feed no responde o no se puede leer.
    """
    if not _CHANNEL_ID.match(channel_id or ""):
        raise ValidationError(f"'{channel_id}' no es un id de canal de YouTube")

    try:
        response = httpx.get(FEED_URL.format(channel_id=channel_id), timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ExternalToolError(
            f"El canal {channel_id} ha respondido {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalToolError(
            f"No se ha podido leer el canal {channel_id}", details={"error": str(exc)}
        ) from exc

    return parse_feed(response.text)


def parse_feed(xml: str) -> list[VideoResult]:
    """Convierte el Atom del canal en vídeos, del más reciente al más antiguo.

    Una entrada rota no tira el feed entero: se salta. Un canal que publica
    algo raro no debe dejar de vigilarse por eso.

    Raises:
        ExternalToolError: si lo que llega no es XML.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ExternalToolError("El canal no ha devuelto un feed legible") from exc

    videos: list[VideoResult] = []
    for entry in root.findall("atom:entry", _NS):
        video_id = entry.findtext("yt:videoId", namespaces=_NS)
        title = entry.findtext("atom:title", namespaces=_NS)
        if not video_id or not title:
            continue

        group = entry.find("media:group", _NS)
        thumbnail = None
        if group is not None:
            node = group.find("media:thumbnail", _NS)
            thumbnail = node.get("url") if node is not None else None

        videos.append(
            VideoResult(
                video_id=video_id,
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                channel=entry.findtext("atom:author/atom:name", namespaces=_NS),
                channel_id=entry.findtext("yt:channelId", namespaces=_NS),
                thumbnail=thumbnail,
                published_at=_parse_date(entry.findtext("atom:published", namespaces=_NS)),
            )
        )

    return sorted(videos, key=_published_key, reverse=True)


# ------------------------------------------------------------------- privado
def _video_from_entry(entry: dict[str, Any] | None) -> VideoResult | None:
    """Traduce un resultado de yt-dlp, o None si no trae ni id ni título."""
    if not entry:
        return None

    video_id = entry.get("id")
    title = entry.get("title")
    if not video_id or not title:
        return None

    return VideoResult(
        video_id=str(video_id),
        title=str(title),
        url=entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        channel=entry.get("channel") or entry.get("uploader"),
        channel_id=entry.get("channel_id"),
        duration=entry.get("duration"),
        view_count=entry.get("view_count"),
        thumbnail=_first_thumbnail(entry),
    )


def _first_thumbnail(entry: dict[str, Any]) -> str | None:
    """La miniatura del resultado, venga como venga.

    En extracción plana yt-dlp unas veces da `thumbnails` y otras `thumbnail`;
    la URL canónica de YouTube funciona siempre y evita depender de eso.
    """
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list) and thumbnails:
        url = thumbnails[-1].get("url")
        if url:
            return str(url)
    if entry.get("thumbnail"):
        return str(entry["thumbnail"])
    return f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"


def _parse_date(value: str | None) -> datetime | None:
    """Fecha ISO del feed, o None si falta o no se entiende."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _published_key(video: VideoResult) -> datetime:
    """Clave de orden que tolera entradas sin fecha, que van al final."""
    if video.published_at is None:
        return datetime.min.replace(tzinfo=None)
    return video.published_at.replace(tzinfo=None)
