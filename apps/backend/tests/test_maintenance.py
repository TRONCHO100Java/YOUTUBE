"""Recuperar sitio y reintentar: lo que NO debe tocar.

Estas dos tareas borran ficheros y reencolan trabajo sin que haya nadie
delante. Lo que se comprueba aqui es justamente donde tienen que pararse.
"""

from __future__ import annotations

import inspect

from clipforge.worker.tasks import maintenance


class TestQueSeBorra:
    def test_solo_toca_proyectos_parados(self) -> None:
        """Borrarle el original a un proyecto a mitad de render lo tumbaria."""
        source = inspect.getsource(maintenance.purge_sources)

        assert "ProjectStatus.COMPLETED" in source
        assert "ProjectStatus.NEEDS_REVIEW" in source
        assert "ProjectStatus.FAILED" in source
        # Los estados en marcha no aparecen por ningun lado.
        for running in ("DOWNLOADING", "TRANSCRIBING", "ANALYZING", "GENERATING_CLIPS"):
            assert running not in source, f"purge_sources mira {running}, que esta en marcha"

    def test_se_puede_desactivar(self) -> None:
        """Con retencion negativa no se borra nada, ni siquiera lo antiguo."""
        result = maintenance.purge_sources(older_than_days=-1)

        assert result["projects"] == 0
        assert result["freed_mb"] == 0

    def test_no_toca_los_clips(self) -> None:
        """Un original se vuelve a bajar de YouTube; un clip renderizado no.

        Si algun dia alguien anade CLIPS a lo borrable, este test cae.
        """
        source = inspect.getsource(maintenance)

        assert "StorageArea.SOURCE" in source
        assert "StorageArea.CLIPS" not in source


class TestQueSeReintenta:
    def test_no_reintenta_lo_que_fallo_por_criterio(self) -> None:
        """NEEDS_REVIEW no es un fallo: la IA miro el video y no vio nada.

        Reintentarlo daria el mismo resultado gastando la misma GPU.
        """
        # Sin el docstring: ahi NEEDS_REVIEW se menciona justo para decir
        # que no se toca, y buscarlo en el texto entero encontraria la
        # explicacion en vez del codigo.
        source = inspect.getsource(maintenance.retry_failed)
        body = source.split('"""')[-1]

        assert "ProjectStatus.FAILED" in body
        assert "NEEDS_REVIEW" not in body

    def test_hay_tope_por_vuelta(self) -> None:
        """Con el disco lleno u Ollama caido, veinte reintentos fallan igual."""
        signature = inspect.signature(maintenance.retry_failed)
        limit = signature.parameters["max_projects"].default

        assert isinstance(limit, int)
        assert 0 < limit <= 20
