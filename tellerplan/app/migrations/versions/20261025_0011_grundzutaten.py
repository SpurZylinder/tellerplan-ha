"""Grundzutaten mit Standardprodukt, Hersteller, übertragbare Kennung eigener Lebensmittel

Revision: 0011
Vorgänger: 0010
Erstellt: 2026-10-25

Bisher zeigte ein gelernter Name direkt auf ein Produkt („milch“ → Produkt). Jetzt zeigt
er auf eine Grundzutat, die das Standardprodukt hält. Vorhandene Zuordnungen werden
übertragen: je Name eine Grundzutat mit dem bisherigen Produkt als Standard; Zeilen,
die genau diesem Standard folgten, zeigen danach auf die Grundzutat ohne eigenes Produkt.

Bewusst ohne App-Code (Modelle können sich später ändern).
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _key(name: str) -> str:
    return " ".join(name.casefold().split())


def upgrade() -> None:
    with op.batch_alter_table("food", schema=None) as batch_op:
        batch_op.add_column(sa.Column("brand", sa.String(length=120), nullable=True))

    op.create_table(
        "base_ingredient",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("default_food_id", sa.Integer(), nullable=True),
        sa.Column("no_nutrients", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["default_food_id"], ["food.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_base_ingredient_default_food_id", "base_ingredient", ["default_food_id"])
    op.create_table(
        "base_ingredient_food",
        sa.Column("base_ingredient_id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["base_ingredient_id"], ["base_ingredient.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["food_id"], ["food.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("base_ingredient_id", "food_id"),
    )
    with op.batch_alter_table("recipe_ingredient", schema=None) as batch_op:
        batch_op.add_column(sa.Column("base_ingredient_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_recipe_ingredient_base_ingredient_id", ["base_ingredient_id"])
        batch_op.create_foreign_key(
            "fk_recipe_ingredient_base_ingredient",
            "base_ingredient",
            ["base_ingredient_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "ingredient_alias_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("base_ingredient_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["base_ingredient_id"], ["base_ingredient.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    _move_aliases()
    op.drop_table("ingredient_alias")
    op.rename_table("ingredient_alias_new", "ingredient_alias")
    op.create_index(
        "ix_ingredient_alias_base_ingredient_id", "ingredient_alias", ["base_ingredient_id"]
    )

    # Übertragbare Kennung für eigene Lebensmittel (BLS: Code, OFF: Barcode)
    connection = op.get_bind()
    custom = connection.execute(
        sa.text("SELECT id FROM food WHERE source = 'custom' AND source_id IS NULL")
    ).scalars()
    for food_id in list(custom):
        connection.execute(
            sa.text("UPDATE food SET source_id = :sid WHERE id = :id"),
            {"sid": uuid.uuid4().hex, "id": food_id},
        )


def _move_aliases() -> None:
    connection = op.get_bind()
    aliases = connection.execute(sa.text("SELECT key, food_id FROM ingredient_alias")).all()
    lines = connection.execute(
        sa.text("SELECT id, name, food_id FROM recipe_ingredient WHERE name IS NOT NULL")
    ).all()
    for key, food_id in aliases:
        base_id = connection.execute(
            sa.text(
                "INSERT INTO base_ingredient (name, key, default_food_id, no_nutrients) "
                "VALUES (:name, :key, :food, 0) RETURNING id"
            ),
            {"name": key.capitalize(), "key": key, "food": food_id},
        ).scalar_one()
        connection.execute(
            sa.text("INSERT INTO base_ingredient_food VALUES (:base, :food)"),
            {"base": base_id, "food": food_id},
        )
        connection.execute(
            sa.text("INSERT INTO ingredient_alias_new (key, base_ingredient_id) VALUES (:k, :b)"),
            {"k": key, "b": base_id},
        )
        for line_id, name, line_food in lines:
            if _key(name) == key and line_food in (food_id, None):
                connection.execute(
                    sa.text(
                        "UPDATE recipe_ingredient SET base_ingredient_id = :base, food_id = NULL "
                        "WHERE id = :id"
                    ),
                    {"base": base_id, "id": line_id},
                )


def downgrade() -> None:
    raise NotImplementedError("Grundzutaten lassen sich nicht verlustfrei zurückbauen.")
