"""Tagebuch je Benutzer

Revision: 0019
Vorgänger: 0018
Erstellt: 2026-11-13

`diary_entry.user_id` hält, wem ein Eintrag gehört (HA-Benutzer-ID). Bestehende
Einträge bleiben leer; ein Verwalter ordnet sie in den Einstellungen einmal zu.
Bewusst ohne Fremdschlüssel: Ein Eintrag bleibt lesbar, auch wenn der Benutzer
(noch) nicht in `app_user` steht.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("diary_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_diary_entry_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("diary_entry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_diary_entry_user_id"))
        batch_op.drop_column("user_id")
