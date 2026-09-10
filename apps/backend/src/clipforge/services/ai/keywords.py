"""Palabras clave que aporta el usuario sobre el vídeo.

Son la única información que el pipeline no puede sacar por su cuenta. El
título de YouTube no suele nombrar a los streamers que salen, la transcripción
menciona apodos que nadie busca, y sin embargo el nombre propio es lo que hace
que un Short aparezca en la búsqueda de alguien. Aquí se limpian y se acotan.

Se guardan tal y como las escribe el usuario y se parten al usarlas, no al
guardarlas: así el campo del formulario devuelve exactamente lo que se tecleó.
"""

from __future__ import annotations

import re

#: Separadores admitidos. Se aceptan comas y saltos de línea porque nadie
#: escribe una lista de la misma forma dos veces.
_SEPARATORS = re.compile(r"[,;\n\r]+")
_WHITESPACE = re.compile(r"\s+")

#: Un término más largo que esto es una frase, no una palabra clave, y en un
#: título ocuparía él solo el espacio disponible.
MAX_TERM_LENGTH = 40

#: Tope de términos. Con más, el modelo deja de priorizar y empieza a meterlos
#: todos a la fuerza en títulos que ya no describen el clip.
MAX_TERMS = 10


def parse_keywords(raw: str | None) -> tuple[str, ...]:
    """Convierte el texto libre del usuario en términos limpios y sin repetir.

    Compara en minúsculas para descartar duplicados pero conserva la forma
    escrita: "Kai Cenat" tiene que llegar al título con sus mayúsculas, porque
    es un nombre propio y así es como se busca.
    """
    if not raw:
        return ()

    terms: list[str] = []
    seen: set[str] = set()

    for chunk in _SEPARATORS.split(raw):
        term = _WHITESPACE.sub(" ", chunk).strip()
        if not term:
            continue
        term = term[:MAX_TERM_LENGTH].strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) == MAX_TERMS:
            break

    return tuple(terms)
