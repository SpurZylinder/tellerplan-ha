"""Alembic-Migrationen aus Python heraus ausführen (Add-on-Start, Tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from settings import Settings

APP_DIR = Path(__file__).resolve().parent


def alembic_config(settings: Settings, skip_data_migrations: bool = False) -> Config:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    config.attributes["settings"] = settings
    config.attributes["skip_data_migrations"] = skip_data_migrations
    return config


def upgrade_to_head(settings: Settings, skip_data_migrations: bool = False) -> None:
    """Migriert auf den neuesten Stand; Datenmigrationen (z. B. BLS) optional auslassen."""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings, skip_data_migrations), "head")
