"""Portionen im Planeintrag

Revision: 0007
Vorgänger: 0006
Erstellt: 2026-10-25

Bestehende Einträge übernehmen die Standardportionen ihres Rezepts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("servings", sa.Float(), nullable=True))
    op.execute(
        "UPDATE plan_entry SET servings = "
        "(SELECT recipe.servings FROM recipe WHERE recipe.id = plan_entry.recipe_id)"
    )
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.alter_column("servings", existing_type=sa.Float(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("plan_entry", schema=None) as batch_op:
        batch_op.drop_column("servings")
