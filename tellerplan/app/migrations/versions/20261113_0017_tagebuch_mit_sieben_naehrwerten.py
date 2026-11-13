"""Tagebuch mit sieben Nährwerten

Revision: 0017
Vorgänger: 0016
Erstellt: 2026-11-13

Der Snapshot eines Tagebucheintrags hielt nur kcal, Eiweiß, Fett und Kohlenhydrate
(Befund K15). Jetzt auch Ballaststoffe, Zucker und Salz. Bestehende Einträge bleiben
leer (unbekannt); sie lassen sich nicht nachholen, weil sich Rezepte seitdem geändert
haben können (Regel 4).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("diary_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fiber_g", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("sugar_g", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("salt_g", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("diary_entry", schema=None) as batch_op:
        batch_op.drop_column("salt_g")
        batch_op.drop_column("sugar_g")
        batch_op.drop_column("fiber_g")
