"""Storage local: nombres seguros, anti path traversal y politica de limpieza."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from clipforge.core.storage import ProjectStorage, StorageArea, sanitize_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("video normal.mp4", "video-normal.mp4"),
        ("Cómo gané 10.000€!!", "Como-gane-10.000"),
        ("../../etc/passwd", "passwd"),
        (r"..\..\windows\system32", "system32"),
        ("   ", "file"),
        ("", "file"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_long_names() -> None:
    assert len(sanitize_filename("a" * 500)) <= 80


def test_layout_creates_every_area(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    root = storage.ensure_layout()
    for area in StorageArea:
        assert (root / area.value).is_dir()


def test_path_for_stays_inside_project(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    path = storage.path_for(StorageArea.SOURCE, "../../escape.mp4")
    assert path.parent == storage.root / "source"
    assert path.name == "escape.mp4"


def test_assert_within_root_rejects_escape(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    storage.ensure_layout()
    with pytest.raises(ValueError, match="fuera del storage"):
        storage.assert_within_root(tmp_path / "otro" / "fichero.mp4")


def test_cleanup_removes_intermediates_but_keeps_clips(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    storage.ensure_layout()
    (storage.root / "clips" / "clip_1.mp4").write_bytes(b"x")
    (storage.root / "temp" / "chunk.ts").write_bytes(b"x")
    (storage.root / "audio" / "audio.wav").write_bytes(b"x")
    (storage.root / "source" / "video.mp4").write_bytes(b"x")

    storage.cleanup(keep_source=False, keep_audio=False)

    assert (storage.root / "clips" / "clip_1.mp4").exists()
    assert not (storage.root / "temp").exists()
    assert not (storage.root / "audio").exists()
    assert not (storage.root / "source").exists()


def test_cleanup_honours_keep_source(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    storage.ensure_layout()
    (storage.root / "source" / "video.mp4").write_bytes(b"x")

    storage.cleanup(keep_source=True, keep_audio=False)

    assert (storage.root / "source" / "video.mp4").exists()


def test_delete_all_removes_project_tree(tmp_path: Path) -> None:
    storage = ProjectStorage(uuid.uuid4(), root=tmp_path)
    storage.ensure_layout()
    storage.delete_all()
    assert not storage.root.exists()
