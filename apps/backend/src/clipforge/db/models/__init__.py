"""Modelos ORM.

Alembic importa este modulo para poblar `Base.metadata`, asi que toda entidad
nueva debe re-exportarse aqui.
"""

from clipforge.db.base import Base
from clipforge.db.models.channel import WatchedChannel
from clipforge.db.models.clip import ClipCandidate, GeneratedClip
from clipforge.db.models.enums import (
    PIPELINE_ORDER,
    CandidateSource,
    CandidateStatus,
    ContentProfile,
    ProjectStatus,
    SourceType,
)
from clipforge.db.models.project import Project
from clipforge.db.models.publish_channel import PublishChannel
from clipforge.db.models.transcript import Transcript, TranscriptSegment

__all__ = [
    "PIPELINE_ORDER",
    "Base",
    "CandidateSource",
    "CandidateStatus",
    "ClipCandidate",
    "ContentProfile",
    "GeneratedClip",
    "Project",
    "ProjectStatus",
    "PublishChannel",
    "SourceType",
    "Transcript",
    "TranscriptSegment",
    "WatchedChannel",
]
