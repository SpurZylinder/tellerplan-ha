"""REWE-Produktnummer an Lebensmitteln

Revision: 0016
Vorgänger: 0015
Erstellt: 2026-11-06

`food.rewe_id` hält die Produktnummer im REWE-Shop, Grundlage für einen späteren
Warenkorb aus der Einkaufsliste. REWE-Produkte ohne Barcode trugen sie schon in der
Quell-ID („rewe-1325124“); die wird übernommen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rewe_id", sa.String(length=20), nullable=True))
        batch_op.create_index(batch_op.f("ix_food_rewe_id"), ["rewe_id"], unique=False)
    op.execute(
        "UPDATE food SET rewe_id = substr(source_id, 6) "
        "WHERE source = 'rewe' AND source_id LIKE 'rewe-%'"
    )


def downgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_food_rewe_id"))
        batch_op.drop_column("rewe_id")
