"""Ziele je Benutzer

Revision: 0020
Vorgänger: 0019
Erstellt: 2026-11-13

`goal` hält die eigenen Tagesziele eines Benutzers ab einem Tag. Ohne Eintrag
gelten die Vorgabeziele aus den Optionen; bestehende Daten ändern sich nicht.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("kcal", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Integer(), nullable=False),
        sa.Column("fat_g", sa.Integer(), nullable=False),
        sa.Column("carbs_g", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "valid_from", name="uq_goal_user_day"),
    )
    op.create_index(op.f("ix_goal_user_id"), "goal", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_goal_user_id"), table_name="goal")
    op.drop_table("goal")
