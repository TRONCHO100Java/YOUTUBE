"""Schemas transversales."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Forma unica de error en toda la API."""

    error: ErrorDetail


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
