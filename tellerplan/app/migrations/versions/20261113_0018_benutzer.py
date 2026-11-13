"""Benutzer

Revision: 0018
Vorgänger: 0017
Erstellt: 2026-11-13

`app_user` merkt sich die Home-Assistant-Benutzer, die Tellerplan geöffnet haben
(Grundlage für Tagebuch und Ziele je Benutzer). Sitzungen der Vollbild-App wissen
jetzt, wer angemeldet ist; ältere Sitzungen ohne Benutzer melden sich neu an.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("web_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("user_name", sa.String(length=200), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(batch_op.f("ix_web_session_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("web_session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_web_session_user_id"))
        batch_op.drop_column("is_admin")
        batch_op.drop_column("user_name")
        batch_op.drop_column("user_id")
    op.drop_table("app_user")
