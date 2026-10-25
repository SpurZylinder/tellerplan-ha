"""Einkaufsliste: gesendet am, je Planeintrag

Revision: 0008
Vorgänger: 0007
Erstellt: 2026-10-25

Merkt sich, wann die Zutaten eines Planeintrags an Bring gingen, damit
erneutes Senden Gekauftes nicht wieder auf die Liste setzt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shopping_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.drop_column("shopping_sent_at")
