"""Canales vigilados: la fuente de vídeos que no hay que ir a buscar.

Un canal dado de alta aqui convierte la aplicacion en algo que corre solo. Cada
poco tiempo se lee su RSS y los videos nuevos entran en la cola sin que nadie
pegue una URL.

La marca de agua es `last_video_published_at`, y es lo unico que impide que la
primera revision de un canal encole sus quince ultimos videos de golpe.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WatchedChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un canal de YouTube cuyos videos nuevos se procesan solos."""

    __tablename__ = "watched_channels"

    #: Id "UC..." del canal. Es lo unico que entiende el RSS, y es unico para
    #: que dar de alta dos veces el mismo canal no lo procese dos veces.
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    #: Apagarlo deja de mirarlo sin perder ni la configuracion ni la marca de
    #: agua, que es lo que hace falta para pausar un canal ruidoso un tiempo.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    #: Filtros previos a la descarga. Bajar 400 MB para descubrir que el video
    #: duraba tres horas es el gasto mas tonto del pipeline.
    min_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_views: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Palabras clave que heredan los proyectos creados desde este canal. Un
    #: canal de un streamer concreto siempre aporta los mismos nombres.
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: A que canal propio van los clips de este. Es lo que convierte
    #: "vigilo a Speed" en "los clips de Speed acaban en mi canal de Speed",
    #: sin depender de que el etiquetador acierte: aqui el destino es
    #: explicito y manda sobre el reparto por etiquetas.
    publish_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publish_channels.id", ondelete="SET NULL"), nullable=True
    )

    #: Marca de agua: fecha de publicacion del video mas reciente que ya se ha
    #: visto. Se fija en el alta con el ultimo video del canal, para que dar de
    #: alta un canal no encole de golpe sus quince ultimos videos.
    last_video_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Cuando se miro por ultima vez y que paso. Sirve para saber si un canal
    #: lleva callado tres dias o es que la revision esta fallando.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Cuantos proyectos ha traido este canal. Es la respuesta a "¿esto sirve
    #: de algo?" sin tener que cruzar tablas.
    projects_created: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    def __repr__(self) -> str:
        return f"<WatchedChannel {self.channel_id} {self.title!r} enabled={self.enabled}>"
