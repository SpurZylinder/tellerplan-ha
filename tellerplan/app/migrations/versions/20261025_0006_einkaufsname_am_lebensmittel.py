"""Einkaufsname am Lebensmittel

Revision: 0006
Vorgänger: 0005
Erstellt: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shopping_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.drop_column("shopping_name")
