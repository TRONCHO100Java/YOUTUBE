"""El cierre de canal: lo que se le escribe encima a la plantilla.

Aqui no se comprueba que el video se vea bien —eso se mira mirandolo— sino lo
que si puede romperse en silencio: que un nombre con caracteres raros no se
cuele en la linea de comandos de ffmpeg, y que el fichero de cada canal sea
suyo y no el de otro.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from clipforge.core.errors import ClipForgeError
from clipforge.services.video.outro import (
    OutroText,
    build_outro,
    escape_text,
    outro_path_for,
    outro_template,
)

CHANNEL = UUID("2f5a1c9e-3d47-4b80-9a12-6e8c07b4d5f1")
OTHER = UUID("7b1d4e02-9c85-4a63-b0f7-1e2d3c4a5b69")


class TestEscapado:
    """`drawtext` parte su argumento por los dos puntos y usa la barra
    invertida como escape: un nombre sin escapar no da un cierre feo, da un
    ffmpeg que falla o que interpreta el texto como parametros suyos."""

    def test_los_dos_puntos_se_escapan(self) -> None:
        assert escape_text("Clips: lo mejor") == r"Clips\: lo mejor"

    def test_la_comilla_simple_se_escapa(self) -> None:
        assert escape_text("Kai's clips") == r"Kai\'s clips"

    def test_el_porcentaje_se_escapa(self) -> None:
        """Sin escapar, `drawtext` lo lee como una expansion tipo strftime."""
        assert escape_text("100% real") == r"100\% real"

    def test_un_nombre_normal_no_se_toca(self) -> None:
        assert escape_text("@ClipRushViralRush") == "@ClipRushViralRush"


class TestRutas:
    def test_cada_canal_tiene_su_fichero(self) -> None:
        """Por id: renombrar un canal no puede hacer que dos se pisen el cierre."""
        assert outro_path_for(CHANNEL) != outro_path_for(OTHER)

    def test_el_fichero_lleva_el_id_del_canal(self) -> None:
        assert outro_path_for(CHANNEL).stem == str(CHANNEL)

    def test_la_plantilla_es_una_sola_para_todos(self) -> None:
        assert outro_template().name == "template.mp4"
        assert outro_template().parent == outro_path_for(CHANNEL).parent


class TestNombreObligatorio:
    def test_sin_nombre_no_se_construye(self, tmp_path: object) -> None:
        """Un cierre sin nombre no distingue un canal de otro, que es lo unico
        para lo que existe. Antes que generar uno inutil, se dice que falta."""
        with pytest.raises(ClipForgeError, match="nombre"):
            build_outro(
                outro_template(),
                outro_path_for(CHANNEL),
                OutroText(handle="   "),
            )

    def test_sin_plantilla_lo_dice_claro(self, tmp_path: object) -> None:
        from pathlib import Path

        missing = Path(str(tmp_path)) / "no_existe.mp4"
        with pytest.raises(ClipForgeError, match="plantilla"):
            build_outro(missing, Path(str(tmp_path)) / "x.mp4", OutroText(handle="@x"))
