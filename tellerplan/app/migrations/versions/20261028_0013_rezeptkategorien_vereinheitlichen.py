"""Rezeptkategorien auf die feste Liste umstellen

Cookidoo lieferte Sammelkategorien; die Kategorie wird jetzt per Auswahl gepflegt.
„Snack/Beilage“ wird zu „Snack“, „Grundrezept/Getränk“ zu „Grundrezept“.

Revision: 0013
Vorgänger: 0012
Erstellt: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Feste Werte dieser Migration (Stand 2026-10-28), nicht aus den Einstellungen
RENAMED = {"Snack/Beilage": "Snack", "Grundrezept/Getränk": "Grundrezept"}

recipe = sa.table("recipe", sa.column("category", sa.String))


def upgrade() -> None:
    for old, new in RENAMED.items():
        op.execute(recipe.update().where(recipe.c.category == old).values(category=new))


def downgrade() -> None:
    # Nach dem Umstellen sind die Kategorien von Hand gepflegt; zurück geht es nicht eindeutig.
    pass
