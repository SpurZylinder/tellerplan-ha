"""Datenbankzugang: Engine, Sessions und deklarative Basis für alle Module."""

import shutil
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from settings import Settings

BACKUP_SUFFIX = ".bak"


class Base(DeclarativeBase):
    """Gemeinsame Basis aller ORM-Modelle."""


def _configure_sqlite(connection: SQLiteConnection, _record: ConnectionPoolEntry) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_engine(settings: Settings) -> Engine:
    """SQLite-Engine mit Fremdschlüsseln und WAL-Journal."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def backup_database(database_path: Path) -> Path | None:
    """Kopiert die Datenbank vor Migrationen; gibt den Pfad der Kopie zurück."""
    if not database_path.exists():
        return None
    backup_path = database_path.with_name(database_path.name + BACKUP_SUFFIX)
    shutil.copy2(database_path, backup_path)
    return backup_path
