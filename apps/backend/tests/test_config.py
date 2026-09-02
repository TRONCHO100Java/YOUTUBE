"""Configuracion: parseo de listas y derivacion de URLs de base de datos."""

from __future__ import annotations

from clipforge.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_lists_accept_csv() -> None:
    settings = _settings(cors_origins="http://a.com, http://b.com")
    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_lists_accept_json() -> None:
    settings = _settings(cors_origins=["http://a.com"])
    assert settings.cors_origins == ["http://a.com"]


def test_database_urls_are_derived_per_driver() -> None:
    settings = _settings(database_url="postgresql://u:p@host:5442/db")
    assert settings.sync_database_url == "postgresql+psycopg://u:p@host:5442/db"
    assert settings.async_database_url == "postgresql+asyncpg://u:p@host:5442/db"


def test_existing_driver_in_url_is_normalized() -> None:
    settings = _settings(database_url="postgresql+asyncpg://u:p@host:5442/db")
    assert settings.database_url == "postgresql://u:p@host:5442/db"
    assert settings.sync_database_url == "postgresql+psycopg://u:p@host:5442/db"
