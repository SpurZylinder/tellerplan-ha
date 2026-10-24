"""Alembic-Migrationen aus Python heraus ausführen (Add-on-Start, Tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from settings import Settings

APP_DIR = Path(__file__).resolve().parent


def alembic_config(settings: Settings) -> Config:
    config = Config(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "migrations"))
    config.attributes["settings"] = settings
    return config


def upgrade_to_head(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings), "head")
