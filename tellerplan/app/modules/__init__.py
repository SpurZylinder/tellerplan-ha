"""Fachmodule. Abhängigkeitsrichtung:

foods ← nutrition ← recipes ← importers, recipes ← planner, (nutrition, planner) ← diary

Der Import der Untermodule registriert ihre Modelle an `db.Base.metadata`
(wichtig für Alembic-Autogenerate).
"""

from modules import diary, foods, importers, nutrition, planner, recipes

__all__ = ["diary", "foods", "importers", "nutrition", "planner", "recipes"]
