from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from db import backup_database, create_db_engine
from migrate import upgrade_to_head
from modules.foods.models import Food, FoodSource
from settings import Settings


def test_migrations_run_to_head(settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)

    engine = create_db_engine(settings)
    assert "alembic_version" in inspect(engine).get_table_names()
    engine.dispose()


def test_backup_copies_existing_database(settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)

    backup = backup_database(settings.database_path)

    assert backup is not None
    assert backup.name == "app.db.bak"
    assert backup.read_bytes() == settings.database_path.read_bytes()


def test_backup_skips_missing_database(settings: Settings) -> None:
    assert backup_database(settings.database_path) is None


def test_bls_migration_imports_foods_once(settings: Settings) -> None:
    upgrade_to_head(settings)
    upgrade_to_head(settings)  # zweiter Lauf darf nichts doppelt anlegen

    engine = create_db_engine(settings)
    with Session(engine) as session:
        count = session.scalar(select(func.count()).where(Food.source == FoodSource.BLS))
        oats = session.scalar(select(Food).where(Food.source_id == "C133000"))
    engine.dispose()

    assert count == 7140
    assert oats is not None
    assert oats.name == "Hafer Flocken"
    assert oats.kcal == 348
