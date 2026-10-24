from sqlalchemy import inspect

from db import backup_database, create_db_engine
from migrate import upgrade_to_head
from settings import Settings


def test_migrations_run_to_head(settings: Settings) -> None:
    upgrade_to_head(settings)

    engine = create_db_engine(settings)
    assert "alembic_version" in inspect(engine).get_table_names()
    engine.dispose()


def test_backup_copies_existing_database(settings: Settings) -> None:
    upgrade_to_head(settings)

    backup = backup_database(settings.database_path)

    assert backup is not None
    assert backup.name == "app.db.bak"
    assert backup.read_bytes() == settings.database_path.read_bytes()


def test_backup_skips_missing_database(settings: Settings) -> None:
    assert backup_database(settings.database_path) is None
