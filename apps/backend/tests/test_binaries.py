"""Resolución de ejecutables multimedia."""

from __future__ import annotations

from pathlib import Path

from clipforge.services.video.binaries import ffmpeg_directory, resolve_binary


def test_resolves_a_command_available_in_path() -> None:
    """Un nombre suelto debe convertirse en ruta absoluta a un fichero real."""
    resolved = resolve_binary("ffmpeg")
    assert resolved is not None, "ffmpeg debe estar instalado y en el PATH"
    assert resolved.is_absolute()
    assert resolved.is_file()


def test_accepts_an_explicit_path(tmp_path: Path) -> None:
    binary = tmp_path / "ffmpeg.exe"
    binary.write_bytes(b"")
    assert resolve_binary(str(binary)) == binary.resolve()


def test_returns_none_when_missing() -> None:
    assert resolve_binary("comando-que-no-existe-clipforge") is None
    assert resolve_binary("") is None


def test_ffmpeg_directory_points_at_the_folder_not_the_binary() -> None:
    """yt-dlp necesita el directorio para encontrar también ffprobe."""
    directory = ffmpeg_directory()
    assert directory is not None, "ffmpeg debe estar instalado y en el PATH"
    assert Path(directory).is_dir()
    assert not Path(directory).is_file()
