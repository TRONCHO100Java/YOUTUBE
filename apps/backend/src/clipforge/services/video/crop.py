"""Geometría del recorte vertical.

FASE 5: recorte centrado, que es el comportamiento razonable por defecto.
La FASE 6 sustituirá `center_crop` por una versión que sitúe la ventana sobre
la cara detectada; el resto del render no tendrá que cambiar, porque solo
consume una `CropWindow`.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.core.errors import ExternalToolError


@dataclass(frozen=True, slots=True)
class CropWindow:
    """Región del vídeo original que acaba dentro del clip vertical."""

    x: int
    y: int
    width: int
    height: int

    def to_filter(self) -> str:
        return f"crop={self.width}:{self.height}:{self.x}:{self.y}"


def center_crop_within(content: CropWindow, target_width: int, target_height: int) -> CropWindow:
    """Recorte centrado dentro de una región concreta del fotograma.

    Se usa para encuadrar dentro de la zona con imagen real cuando el vídeo
    trae letterbox incrustado: así las barras negras no acaban en el clip.
    """
    window = center_crop(content.width, content.height, target_width, target_height)
    return CropWindow(
        x=content.x + window.x,
        y=content.y + window.y,
        width=window.width,
        height=window.height,
    )


def center_crop(
    source_width: int, source_height: int, target_width: int, target_height: int
) -> CropWindow:
    """Mayor ventana con la proporción de salida que cabe centrada en la fuente.

    Con una fuente 16:9 recorta los laterales; con una fuente ya vertical y más
    estrecha que 9:16, recorta arriba y abajo.

    Raises:
        ExternalToolError: si alguna dimensión no es positiva.
    """
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ExternalToolError(
            "Dimensiones inválidas para el recorte",
            details={
                "source": f"{source_width}x{source_height}",
                "target": f"{target_width}x{target_height}",
            },
        )

    target_ratio = target_width / target_height

    if source_width / source_height > target_ratio:
        # Fuente más ancha de lo necesario: se conserva toda la altura.
        width = _even(source_height * target_ratio)
        height = _even(source_height)
    else:
        width = _even(source_width)
        height = _even(source_width / target_ratio)

    width = min(width, _even(source_width))
    height = min(height, _even(source_height))

    return CropWindow(
        x=_even((source_width - width) / 2),
        y=_even((source_height - height) / 2),
        width=width,
        height=height,
    )


def _even(value: float) -> int:
    """H.264 exige dimensiones pares; un impar hace fallar el codificador."""
    return max(0, int(value) // 2 * 2)
