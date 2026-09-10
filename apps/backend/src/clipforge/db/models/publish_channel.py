"""Canales de destino: donde se publica cada clip.

No confundir con `WatchedChannel`, que es de donde SALEN los videos. Este es el
otro extremo del flujo: los canales propios a los que van los clips ya hechos.

La razon de que exista es la regla de producto de siempre: un canal de Shorts
funciona cuando lo que publica se parece entre si. Con varios canales a la vez
—uno de Speed, otro de Among Us, otro de comedia— hace falta decidir que clip
va a cual, y decidirlo a mano cinco veces por video no escala.

El reparto se apoya en las etiquetas que ya pone el etiquetador (fase 23):
nicho, quien sale, temas y clase de momento. Aqui solo se declara que quiere
cada canal, y el enrutador cruza las dos cosas.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PublishChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un canal propio de YouTube al que se suben clips."""

    __tablename__ = "publish_channels"

    #: Como lo llamas tu, no como se llama en YouTube. Es lo que se lee en la
    #: interfaz al decir "este clip va a Speed Clips".
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: URL del canal. Es lo que se abre para subir, asi que se guarda tal cual
    #: la pega el usuario en vez de reconstruirla desde un id.
    #:
    #: Opcional a proposito: la linea editorial se decide antes de que el
    #: canal exista en YouTube. Obligarla forzaria a inventarse una URL
    #: falsa para poder empezar a repartir clips.
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Id "UC..." si se ha podido resolver. Sirve para distinguir dos canales
    #: con el mismo nombre; no es imprescindible para subir.
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Apagarlo deja de enrutarle clips sin perder su configuracion.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # ------------------------------------------------------ que quiere este canal
    #: Nicho que acepta. Vacio = cualquiera.
    niche: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Personas cuyos clips van aqui: ["speed"], ["kai cenat"]. Vacio =
    #: cualquiera. Basta con que el clip mencione UNA de ellas.
    people: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Temas que acepta. Misma regla: basta con uno.
    topics: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Clases de momento que acepta: ["fail", "reaccion"]. Vacio = cualquiera.
    kinds: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Nota minima para que un clip sea digno de ESTE canal. Puede ser mas
    #: exigente que la del sistema: un canal principal y uno de descartes no
    #: tienen por que publicar lo mismo.
    min_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)

    #: A igualdad de encaje, gana el de prioridad mas alta. Sin esto, un clip
    #: que cuadra en dos canales dependeria del orden de la consulta.
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    #: Notas del usuario sobre la linea editorial del canal. No se usa para
    #: enrutar: es para acordarse de por que existe este canal.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<PublishChannel {self.name!r} enabled={self.enabled}>"
