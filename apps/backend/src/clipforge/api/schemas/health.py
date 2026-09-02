"""Schemas de health check."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "degraded", "error"]


class ComponentHealth(BaseModel):
    status: Status
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Status
    app: str
    version: str
    environment: str


class ReadinessResponse(HealthResponse):
    components: dict[str, ComponentHealth]
