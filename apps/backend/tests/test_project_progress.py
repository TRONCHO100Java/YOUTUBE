"""Progreso derivado del estado del proyecto."""

from __future__ import annotations

from clipforge.api.schemas.project import compute_progress
from clipforge.db.models.enums import PIPELINE_ORDER, ProjectStatus


def test_created_is_zero_and_completed_is_one() -> None:
    assert compute_progress(ProjectStatus.CREATED) == 0.0
    assert compute_progress(ProjectStatus.COMPLETED) == 1.0


def test_failed_reports_no_progress() -> None:
    assert compute_progress(ProjectStatus.FAILED) == 0.0


def test_progress_is_monotonic_along_the_pipeline() -> None:
    values = [compute_progress(status) for status in PIPELINE_ORDER]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_terminal_and_running_flags() -> None:
    assert ProjectStatus.COMPLETED.is_terminal
    assert ProjectStatus.FAILED.is_terminal
    assert not ProjectStatus.CREATED.is_running
    assert ProjectStatus.TRANSCRIBING.is_running
