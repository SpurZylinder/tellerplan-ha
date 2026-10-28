"""Toleranter Schlüssel für Zutatennamen und Grundzutaten

Der Schlüssel ignoriert jetzt auch ß/ss, Bindestrich/Leerzeichen und die Mehrzahl des
letzten Wortes („Zwiebeln“ = „Zwiebel“). Die Migration
1. führt Grundzutaten zusammen, die danach denselben Schlüssel haben. Es bleibt die
   mit mehr Rezeptzeilen. Zeilen der anderen, deren Standardprodukt abweicht,
   bekommen dieses Produkt fest, damit sich keine Nährwerte ändern;
2. rechnet die Schlüssel von Grundzutaten und gelernten Namen neu (bei doppelten
   Namen bleibt der der meistgenutzten Grundzutat);
3. ordnet offene Zeilen zu, deren Name jetzt einen gelernten Namen trifft.

Revision: 0014
Vorgänger: 0013
Erstellt: 2026-10-29
"""

from collections import defaultdict
from collections.abc import Sequence

from alembic import op
from sqlalchemy import Connection, text

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Eingefroren (Stand 2026-10-29), unabhängig von späteren Änderungen an alias_key
PLURAL_ENDINGS = ("en", "n", "e", "s")
MIN_STEM_LENGTH = 4


def _key(name: str) -> str:
    words = name.casefold().replace("-", " ").split()
    if words:
        word = words[-1]
        for ending in PLURAL_ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM_LENGTH:
                words[-1] = word[: -len(ending)]
                break
    return " ".join(words)


def _line_counts(connection: Connection) -> dict[int, int]:
    rows = connection.execute(
        text(
            "SELECT base_ingredient_id, count(*) FROM recipe_ingredient "
            "WHERE base_ingredient_id IS NOT NULL GROUP BY base_ingredient_id"
        )
    )
    return {base_id: count for base_id, count in rows}


def _merge(connection: Connection, loser: int, survivor: int) -> None:
    defaults = dict(
        connection.execute(
            text("SELECT id, default_food_id FROM base_ingredient WHERE id IN (:a, :b)"),
            {"a": loser, "b": survivor},
        ).all()
    )
    loser_default, survivor_default = defaults[loser], defaults[survivor]
    if survivor_default is None and loser_default is not None:
        connection.execute(
            text("UPDATE base_ingredient SET default_food_id = :food WHERE id = :id"),
            {"food": loser_default, "id": survivor},
        )
        survivor_default = loser_default
    if loser_default is not None and loser_default != survivor_default:
        # Diese Zeilen rechneten bisher mit dem Standard der anderen Grundzutat
        connection.execute(
            text(
                "UPDATE recipe_ingredient SET food_id = :food "
                "WHERE base_ingredient_id = :loser AND food_id IS NULL"
            ),
            {"food": loser_default, "loser": loser},
        )
    connection.execute(
        text("UPDATE recipe_ingredient SET base_ingredient_id = :s WHERE base_ingredient_id = :l"),
        {"s": survivor, "l": loser},
    )
    connection.execute(
        text("UPDATE ingredient_alias SET base_ingredient_id = :s WHERE base_ingredient_id = :l"),
        {"s": survivor, "l": loser},
    )
    connection.execute(
        text(
            "INSERT OR IGNORE INTO base_ingredient_food (base_ingredient_id, food_id) "
            "SELECT :s, food_id FROM base_ingredient_food WHERE base_ingredient_id = :l"
        ),
        {"s": survivor, "l": loser},
    )
    # Fremdschlüssel sind während der Migration aus (env.py), also von Hand aufräumen
    connection.execute(
        text("DELETE FROM base_ingredient_food WHERE base_ingredient_id = :l"), {"l": loser}
    )
    connection.execute(text("DELETE FROM base_ingredient WHERE id = :l"), {"l": loser})


def _merge_bases(connection: Connection) -> None:
    counts = _line_counts(connection)
    groups: dict[str, list[int]] = defaultdict(list)
    for base_id, name in connection.execute(text("SELECT id, name FROM base_ingredient")):
        groups[_key(name)].append(base_id)
    for ids in groups.values():
        survivor, *losers = sorted(ids, key=lambda base_id: (-counts.get(base_id, 0), base_id))
        for loser in losers:
            _merge(connection, loser, survivor)
    for base_id, name in connection.execute(text("SELECT id, name FROM base_ingredient")).all():
        connection.execute(
            text("UPDATE base_ingredient SET key = :key WHERE id = :id"),
            {"key": _key(name), "id": base_id},
        )


def _rekey_aliases(connection: Connection) -> None:
    counts = _line_counts(connection)
    aliases = connection.execute(
        text("SELECT id, key, base_ingredient_id FROM ingredient_alias")
    ).all()
    by_key: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for alias_id, key, base_id in aliases:
        by_key[_key(key)].append((alias_id, base_id))
    # Erst alle löschen, dann neu schreiben: so stört der eindeutige Index nicht
    connection.execute(text("DELETE FROM ingredient_alias"))
    for key, entries in by_key.items():
        alias_id, base_id = min(entries, key=lambda e: (-counts.get(e[1], 0), e[0]))
        connection.execute(
            text(
                "INSERT INTO ingredient_alias (id, key, base_ingredient_id, updated_at) "
                "VALUES (:id, :key, :base, CURRENT_TIMESTAMP)"
            ),
            {"id": alias_id, "key": key, "base": base_id},
        )


def _link_open_lines(connection: Connection) -> None:
    rows = connection.execute(text("SELECT key, base_ingredient_id FROM ingredient_alias")).all()
    aliases = {key: base_id for key, base_id in rows}
    open_lines = connection.execute(
        text(
            "SELECT id, coalesce(name, raw_text) FROM recipe_ingredient "
            "WHERE base_ingredient_id IS NULL AND food_id IS NULL"
        )
    ).all()
    for line_id, name in open_lines:
        base_id = aliases.get(_key(name))
        if base_id is not None:
            connection.execute(
                text("UPDATE recipe_ingredient SET base_ingredient_id = :b WHERE id = :id"),
                {"b": base_id, "id": line_id},
            )


def upgrade() -> None:
    connection = op.get_bind()
    _merge_bases(connection)
    _rekey_aliases(connection)
    _link_open_lines(connection)


def downgrade() -> None:
    # Zusammengeführte Grundzutaten lassen sich nicht wieder trennen.
    pass
