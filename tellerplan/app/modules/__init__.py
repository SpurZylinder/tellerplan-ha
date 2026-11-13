"""Fachmodule. Abhängigkeitsrichtung:

foods ← nutrition ← recipes ← importers, recipes ← planner, (nutrition, planner, users) ← diary
users: bekannte Benutzer aus Home Assistant, hängt von keinem Fachmodul ab

Der Import der Untermodule registriert ihre Modelle an `db.Base.metadata`
(wichtig für Alembic-Autogenerate).
"""

from modules import diary, foods, importers, nutrition, planner, recipes, users

__all__ = ["diary", "foods", "importers", "nutrition", "planner", "recipes", "users"]
