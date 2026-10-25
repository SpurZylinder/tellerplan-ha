"""Zutatenname, gelernte Standardartikel und Vergleichswerte der Quelle

Revision: 0010
Vorgänger: 0009
Erstellt: 2026-10-25

Bestehende Zutatenzeilen bekommen den Namen ihres Lebensmittels.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recipe_ingredient", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=200), nullable=True))
    op.execute(
        "UPDATE recipe_ingredient SET name = "
        "(SELECT food.name FROM food WHERE food.id = recipe_ingredient.food_id) "
        "WHERE food_id IS NOT NULL"
    )
    op.create_index("uq_recipe_source_id", "recipe", ["source", "source_id"], unique=True)

    op.create_table(
        "ingredient_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["food_id"], ["food.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    with op.batch_alter_table("ingredient_alias", schema=None) as batch_op:
        batch_op.create_index("ix_ingredient_alias_food_id", ["food_id"])

    op.create_table(
        "recipe_reference",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=True),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("recipe_id"),
    )


def downgrade() -> None:
    op.drop_table("recipe_reference")
    op.drop_table("ingredient_alias")
    op.drop_index("uq_recipe_source_id", table_name="recipe")
    with op.batch_alter_table("recipe_ingredient", schema=None) as batch_op:
        batch_op.drop_column("name")
