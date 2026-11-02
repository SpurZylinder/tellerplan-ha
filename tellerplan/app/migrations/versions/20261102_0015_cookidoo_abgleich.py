"""Cookidoo-Abgleich: Tag in Cookidoo je Planeintrag, Notizen zum Entfernen

Revision: 0015
Vorgänger: 0014
Erstellt: 2026-11-02

`plan_entry.cookidoo_day` hält den Tag, an dem der Eintrag beim letzten Abgleich in
Cookidoo stand (leer = nie abgeglichen). Daran erkennt der Abgleich, ob Tellerplan
oder Cookidoo ein Rezept verschoben hat. `cookidoo_removal` merkt sich in Tellerplan
gelöschte abgeglichene Einträge, bis der nächste Abgleich sie in Cookidoo entfernt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cookidoo_day", sa.Date(), nullable=True))
    op.create_table(
        "cookidoo_removal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("cookidoo_id", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cookidoo_removal")
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.drop_column("cookidoo_day")
