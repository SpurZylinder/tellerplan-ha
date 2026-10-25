"""Barcode und Packungsgröße am Lebensmittel

Revision: 0012
Vorgänger: 0011
Erstellt: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.add_column(sa.Column("barcode", sa.String(length=14), nullable=True))
        batch_op.add_column(sa.Column("package", sa.String(length=60), nullable=True))
    # Eindeutig, aber mehrere Lebensmittel ohne Barcode (NULL) sind erlaubt
    op.create_index("ix_food_barcode", "food", ["barcode"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_food_barcode", table_name="food")
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.drop_column("package")
        batch_op.drop_column("barcode")
