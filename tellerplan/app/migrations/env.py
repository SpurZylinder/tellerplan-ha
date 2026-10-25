"""Alembic-Umgebung: Datenbank aus settings.py, Schema aus allen Modulmodellen."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

import modules  # noqa: F401 – registriert alle Modelle an Base.metadata
import web_sessions  # noqa: F401 – Sitzungen der Vollbild-App
from db import Base, create_db_engine
from settings import Settings, get_settings

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _settings() -> Settings:
    return config.attributes.get("settings") or get_settings()


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite kann ALTER TABLE nur eingeschränkt
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=_settings().database_url)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(_settings())
    with engine.connect() as connection:
        # SQLite baut Tabellen für manche Änderungen neu auf (kopieren, löschen,
        # umbenennen). Mit aktiven Fremdschlüsseln würde das Löschen per CASCADE
        # abhängige Zeilen mitnehmen, z. B. alle Planeinträge eines Rezepts.
        # Das Pragma wirkt nur außerhalb einer Transaktion.
        # commit() beendet die von SQLAlchemy automatisch begonnene Transaktion,
        # sonst hielte Alembic die Migration für Teil einer äußeren und schriebe nichts fest.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
