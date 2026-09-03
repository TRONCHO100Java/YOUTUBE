"""Carpeta de exportacion: nombres legibles sobre los mismos ficheros.

El almacenamiento interno usa nombres opacos a proposito. Esta vista existe
para poder abrir la carpeta y subir los clips sin adivinar cual es cual.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from clipforge.services import export as export_module
from clipforge.services.export import (
    MARKER_NAME,
    ClipExport,
    export_filename,
    export_project,
)

PROJECT = UUID("c06b25d5-068b-428c-a33f-70a41b65f76e")


@pytest.fixture(autouse=True)
def export_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "export"
    monkeypatch.setattr(export_module, "export_root", lambda: root.resolve())
    return root.resolve()


def _clip(tmp_path: Path, rank: int, title: str, *, subtitles: bool = True) -> ClipExport:
    video = tmp_path / f"clip_{rank:02d}.mp4"
    video.write_bytes(b"video" * 100)
    srt = None
    if subtitles:
        srt = tmp_path / f"clip_{rank:02d}.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhola\n", encoding="utf-8")
    return ClipExport(rank=rank, title=title, video=video, subtitles=srt)


# ------------------------------------------------------------------- nombres


def test_keeps_accents_and_spaces() -> None:
    """Es lo que separa esta funcion de la que nombra el storage interno."""
    assert export_filename("El negocio de la incineración") == "El negocio de la incineración"


def test_colon_becomes_a_dash() -> None:
    """Windows lo prohibe, pero separa dos ideas: borrarlo pega las palabras."""
    assert export_filename("El negocio de la muerte: ¿Cuánto vale?") == (
        "El negocio de la muerte - ¿Cuánto vale"
    )


@pytest.mark.parametrize("char", ["<", ">", ":", '"', "/", "\\", "|", "?", "*"])
def test_characters_forbidden_by_windows_are_removed(char: str) -> None:
    assert char not in export_filename(f"antes{char}despues")


def test_path_separators_cannot_escape() -> None:
    """Un titulo lo escribe un LLM: no puede convertirse en una ruta."""
    name = export_filename("../../etc/passwd")
    assert "/" not in name
    assert "\\" not in name
    assert name not in {".", ".."}


def test_control_characters_are_removed() -> None:
    assert export_filename("titulo\x00con\x1fbasura") == "tituloconbasura"


def test_reserved_device_names_fall_back() -> None:
    """En Windows no existe ningun fichero que se pueda llamar CON.mp4."""
    assert export_filename("CON", fallback="clip 1") == "clip 1"
    assert export_filename("con.mp4", fallback="clip 1") == "clip 1"


def test_empty_or_symbol_only_title_falls_back() -> None:
    assert export_filename("", fallback="clip 3") == "clip 3"
    assert export_filename("???", fallback="clip 3") == "clip 3"


def test_trailing_dots_and_spaces_are_trimmed() -> None:
    """Windows los recorta en silencio; mejor que la ruta sea la que pedimos."""
    assert export_filename("Un titulo... ") == "Un titulo"


def test_long_titles_are_capped() -> None:
    assert len(export_filename("palabra " * 40)) <= 90


# ---------------------------------------------------------------- exportado


def test_creates_the_folder_named_after_the_video(tmp_path: Path, export_root: Path) -> None:
    folder = export_project(PROJECT, "El NEGOCIO de la MUERTE", [_clip(tmp_path, 1, "Uno")])

    assert folder == export_root / "El NEGOCIO de la MUERTE"
    assert folder.is_dir()


def test_clips_are_named_and_ordered_by_rank(tmp_path: Path) -> None:
    folder = export_project(
        PROJECT,
        "Podcast",
        [_clip(tmp_path, 2, "Segundo momento"), _clip(tmp_path, 1, "Primer momento")],
    )
    assert folder is not None

    names = sorted(p.name for p in folder.glob("*.mp4"))
    assert names == ["01 - Primer momento.mp4", "02 - Segundo momento.mp4"]


def test_subtitles_travel_with_the_clip(tmp_path: Path) -> None:
    folder = export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento")])
    assert folder is not None

    assert (folder / "01 - Momento.srt").is_file()


def test_clip_without_subtitles_is_still_exported(tmp_path: Path) -> None:
    folder = export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento", subtitles=False)])
    assert folder is not None

    assert (folder / "01 - Momento.mp4").is_file()
    assert list(folder.glob("*.srt")) == []


def test_content_matches_the_original(tmp_path: Path) -> None:
    clip = _clip(tmp_path, 1, "Momento")
    folder = export_project(PROJECT, "Podcast", [clip])
    assert folder is not None

    assert (folder / "01 - Momento.mp4").read_bytes() == clip.video.read_bytes()


def test_does_not_duplicate_bytes_on_the_same_volume(tmp_path: Path) -> None:
    """Exportar 15 clips no puede costar otro giga de disco."""
    clip = _clip(tmp_path, 1, "Momento")
    folder = export_project(PROJECT, "Podcast", [clip])
    assert folder is not None

    exported = folder / "01 - Momento.mp4"
    assert os.stat(exported).st_ino == os.stat(clip.video).st_ino


def test_reexport_replaces_the_previous_contents(tmp_path: Path) -> None:
    """Un reproceso genera otros clips: los viejos no pueden quedarse."""
    export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento antiguo")])
    folder = export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento nuevo")])
    assert folder is not None

    assert [p.name for p in folder.glob("*.mp4")] == ["01 - Momento nuevo.mp4"]


def test_two_projects_with_the_same_title_do_not_mix(tmp_path: Path) -> None:
    other = uuid4()
    first = export_project(PROJECT, "Mismo titulo", [_clip(tmp_path, 1, "De A")])
    second = export_project(other, "Mismo titulo", [_clip(tmp_path, 1, "De B")])

    assert first != second
    assert second is not None and str(other)[:8] in second.name


def test_a_foreign_folder_is_left_alone(tmp_path: Path, export_root: Path) -> None:
    """Si EXPORT_PATH apunta a una carpeta con cosas, no la vaciamos."""
    intruder = export_root / "Podcast"
    intruder.mkdir(parents=True)
    (intruder / "mio.txt").write_text("no me borres", encoding="utf-8")

    export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento")])

    assert (intruder / "mio.txt").is_file()


def test_marker_records_the_owner(tmp_path: Path) -> None:
    folder = export_project(PROJECT, "Podcast", [_clip(tmp_path, 1, "Momento")])
    assert folder is not None

    assert (folder / MARKER_NAME).read_text(encoding="utf-8").strip() == str(PROJECT)


def test_project_without_title_uses_its_id(tmp_path: Path) -> None:
    folder = export_project(PROJECT, None, [_clip(tmp_path, 1, "Momento")])
    assert folder is not None

    assert str(PROJECT)[:8] in folder.name


def test_no_clips_creates_nothing(export_root: Path) -> None:
    assert export_project(PROJECT, "Podcast", []) is None
    assert not export_root.exists()


def test_a_missing_file_does_not_abort_the_rest(tmp_path: Path) -> None:
    """Un clip borrado a mano no puede impedir exportar los demas."""
    ghost = ClipExport(rank=1, title="Fantasma", video=tmp_path / "no-existe.mp4")
    folder = export_project(PROJECT, "Podcast", [ghost, _clip(tmp_path, 2, "Real")])
    assert folder is not None

    assert [p.name for p in folder.glob("*.mp4")] == ["02 - Real.mp4"]


def test_export_dir_follows_storage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin EXPORT_PATH la carpeta cuelga del storage, no de una ruta fija."""
    from clipforge.core.config import Settings

    settings = Settings(storage_path=tmp_path / "datos", export_path=None)
    assert settings.export_dir == tmp_path / "datos" / "export"


def test_relative_paths_are_anchored_to_the_repo() -> None:
    """El backend se arranca desde varios directorios: el cwd no vale."""
    from clipforge.core.config import Settings
    from clipforge.core.paths import REPO_ROOT

    settings = Settings(export_path=Path("storage/export"))
    assert settings.export_path == (REPO_ROOT / "storage" / "export").resolve()
