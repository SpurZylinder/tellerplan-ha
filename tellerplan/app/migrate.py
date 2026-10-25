"""Alembic-Migrationen aus Python heraus ausführen (Add-on-Start, Tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from settings import Settings

APP_DIR = Path(__file__).resolve().parent


def alembic_config(settings: Settings, skip_data_migrations: bool = False) -> Config:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    config.attributes["settings"] = settings
    config.attributes["skip_data_migrations"] = skip_data_migrations
    return config


def has_pending_migrations(settings: Settings) -> bool:
    """True, wenn die Datenbank existiert und nicht auf dem neuesten Stand ist."""
    if not settings.database_path.exists():
        return False
    head = ScriptDirectory.from_config(alembic_config(settings)).get_current_head()
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    return current != head


def upgrade_to_head(settings: Settings, skip_data_migrations: bool = False) -> None:
    """Migriert auf den neuesten Stand; Datenmigrationen (z. B. BLS) optional auslassen."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings, skip_data_migrations), "head")
