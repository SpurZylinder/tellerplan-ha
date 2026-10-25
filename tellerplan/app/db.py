"""Datenbankzugang: Engine, Sessions und deklarative Basis für alle Module."""

import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from settings import Settings

BACKUP_SUFFIX = ".bak"
# So viele Sicherungen vor Migrationen bleiben liegen; ältere werden gelöscht.
BACKUPS_TO_KEEP = 3


class Base(DeclarativeBase):
    """Gemeinsame Basis aller ORM-Modelle."""


WORD_PATTERN = re.compile(r"\w+")


def search_words(text: str) -> list[str]:
    """Wörter in Kleinschreibung (Unicode, also auch Umlaute), ohne Satzzeichen."""
    return WORD_PATTERN.findall(text.casefold())


def search_key(text: str | None) -> str | None:
    """Suchschlüssel: Wörter zusammengeschrieben, z. B. „Hafer Flocken“ → „haferflocken“."""
    return "".join(search_words(text)) if text is not None else None


def _configure_sqlite(connection: SQLiteConnection, _record: ConnectionPoolEntry) -> None:
    # SQLites lower() kennt keine Umlaute; search_key() normalisiert in Python.
    connection.create_function("search_key", 1, search_key, deterministic=True)
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


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI-Abhängigkeit: eine Session pro Anfrage."""
    with request.app.state.session_factory() as session:
        yield session


def backup_database(database_path: Path, now: datetime | None = None) -> Path | None:
    """Sichert die Datenbank vor Migrationen, z. B. nach `app.db.20261025-101530.bak`.

    Nutzt die Backup-Funktion von SQLite statt einer Dateikopie, damit auch
    Änderungen aus der WAL-Datei enthalten sind. Die letzten `BACKUPS_TO_KEEP`
    Sicherungen bleiben erhalten. Gibt den Pfad der Sicherung zurück.
    """
    if not database_path.exists():
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(f"{database_path.name}.{stamp}{BACKUP_SUFFIX}")
    source = sqlite3.connect(database_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    _remove_old_backups(database_path)
    return backup_path


def _remove_old_backups(database_path: Path) -> None:
    pattern = f"{database_path.name}.*{BACKUP_SUFFIX}"
    backups = sorted(database_path.parent.glob(pattern))
    for old in backups[:-BACKUPS_TO_KEEP]:
        old.unlink()
