import sqlite3
from datetime import datetime, timedelta

from alembic import command
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from db import BACKUPS_TO_KEEP, backup_database, create_db_engine
from migrate import alembic_config, has_pending_migrations, upgrade_to_head
from modules.foods.models import Food, FoodSource
from settings import Settings


def test_migrations_run_to_head(settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)

    engine = create_db_engine(settings)
    assert "alembic_version" in inspect(engine).get_table_names()
    engine.dispose()


def test_backup_contains_changes_still_in_wal(settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)
    writer = sqlite3.connect(settings.database_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE marker (value TEXT)")
    writer.execute("INSERT INTO marker VALUES ('noch im WAL')")
    writer.commit()  # Verbindung bleibt offen, kein Checkpoint

    backup = backup_database(settings.database_path, now=datetime(2026, 10, 25, 10, 15, 30))
    writer.close()

    assert backup is not None
    assert backup.name == "app.db.20261025-101530.bak"
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT value FROM marker").fetchall() == [("noch im WAL",)]
    copy.close()


def test_only_the_latest_backups_are_kept(settings: Settings) -> None:
    upgrade_to_head(settings, skip_data_migrations=True)
    start = datetime(2026, 10, 25, 8, 0)

    backups = [
        backup_database(settings.database_path, now=start + timedelta(hours=hour))
        for hour in range(BACKUPS_TO_KEEP + 2)
    ]

    remaining = sorted(settings.database_path.parent.glob("app.db.*.bak"))
    assert remaining == backups[-BACKUPS_TO_KEEP:]


def test_pending_migrations_are_detected(settings: Settings) -> None:
    assert not has_pending_migrations(settings)  # noch keine Datenbank

    command.upgrade(alembic_config(settings, skip_data_migrations=True), "0006")
    assert has_pending_migrations(settings)

    upgrade_to_head(settings, skip_data_migrations=True)
    assert not has_pending_migrations(settings)


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


def test_migration_0007_fills_plan_servings_from_recipe(settings: Settings) -> None:
    command.upgrade(alembic_config(settings, skip_data_migrations=True), "0006")
    connection = sqlite3.connect(settings.database_path)
    connection.execute(
        "INSERT INTO recipe (id, title, source, servings, is_favorite) "
        "VALUES (1, 'Chili', 'manual', 4, 0)"
    )
    connection.execute("INSERT INTO plan_entry (id, day, recipe_id) VALUES (1, '2026-10-25', 1)")
    connection.commit()
    connection.close()

    upgrade_to_head(settings, skip_data_migrations=True)

    connection = sqlite3.connect(settings.database_path)
    assert connection.execute("SELECT servings FROM plan_entry").fetchall() == [(4.0,)]
    connection.close()
