"""Lebensmittel aus BLS 4.0 einspielen

Revision: 0005
Vorgänger: 0004
Erstellt: 2026-10-24

Datenmigration: liest data/bls_4_0.csv und legt die Lebensmittel mit
source = "bls" und dem BLS-Code als source_id an. Vorhandene BLS-Einträge
werden über den Code aktualisiert, damit Verweise aus Rezepten erhalten bleiben.

Bewusst ohne App-Code (Modelle können sich später ändern). Tests können den
Import über config.attributes["skip_data_migrations"] überspringen.
"""

import csv
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.sqlite import insert

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "bls_4_0.csv"
SOURCE = "bls"
NUTRIENTS = ("kcal", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugar_g", "salt_g")
REQUIRED = {"kcal", "protein_g", "fat_g", "carbs_g"}
BATCH_SIZE = 500

food = sa.table(
    "food",
    sa.column("name", sa.String),
    sa.column("source", sa.String),
    sa.column("source_id", sa.String),
    *(sa.column(name, sa.Float) for name in NUTRIENTS),
)


def _skip() -> bool:
    return bool(op.get_context().config.attributes.get("skip_data_migrations"))


def _value(row: dict[str, str], field: str) -> float | None:
    text = row[field].strip()
    if not text:
        return 0.0 if field in REQUIRED else None
    return float(text)


def _records() -> list[dict[str, object]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as file:
        return [
            {
                "name": row["name"],
                "source": SOURCE,
                "source_id": row["bls_code"],
                **{field: _value(row, field) for field in NUTRIENTS},
            }
            for row in csv.DictReader(file)
        ]


def upgrade() -> None:
    if _skip():
        return
    records = _records()
    connection = op.get_bind()
    for start in range(0, len(records), BATCH_SIZE):
        statement = insert(food).values(records[start : start + BATCH_SIZE])
        statement = statement.on_conflict_do_update(
            index_elements=["source", "source_id"],
            set_={field: statement.excluded[field] for field in ("name", *NUTRIENTS)},
        )
        connection.execute(statement)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM food WHERE source = :source").bindparams(source=SOURCE))
