"""Legt ein Demo-Set an Lebensmitteln und Rezepten an (mehrfach ausführbar).

Aufruf in tellerplan/app:  python -m scripts.seed_demo

Die Nährwerte sind gerundete Näherungen für gängige Produkte, gedacht zum
Ausprobieren, bis der BLS-Import kommt. Alle Einträge tragen `source_id`
mit dem Präfix „demo:“ und lassen sich daran später erkennen.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import create_db_engine, create_session_factory
from migrate import upgrade_to_head
from modules.foods.models import Food, FoodSource
from modules.foods.service import FoodInput, create_food, find_by_source, set_unit
from modules.recipes.models import Recipe
from modules.recipes.service import IngredientInput, RecipeInput, add_ingredient, create_recipe
from settings import get_settings

DEMO_PREFIX = "demo:"
DEMO_SOURCE = "demo"

# slug: (Name, kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz) pro 100 g, Einheiten in g
FOODS: dict[str, tuple[tuple[str, float, float, float, float, float, float, float], dict]] = {
    "skyr": (("Skyr natur", 63, 11, 0.2, 4, 0, 4, 0.1), {"Becher": 450}),
    "magerquark": (("Magerquark", 67, 12, 0.3, 4, 0, 4, 0.1), {"Becher": 250}),
    "huettenkaese": (("Hüttenkäse", 100, 12.5, 4.5, 2.5, 0, 2.5, 0.7), {"Becher": 200}),
    "heidelbeeren": (("Heidelbeeren", 42, 0.6, 0.6, 7.4, 4.9, 7.4, 0), {"Handvoll": 50}),
    "haferflocken": (("Haferflocken", 370, 13.5, 7, 59, 10, 1, 0), {"EL": 10}),
    "honig": (("Honig", 310, 0.4, 0, 75, 0, 75, 0), {"TL": 7, "EL": 20}),
    "haehnchenbrust": (("Hähnchenbrustfilet, roh", 105, 23.5, 1.2, 0, 0, 0, 0.15), {}),
    "reis": (("Basmatireis, roh", 350, 8, 0.6, 77, 1.4, 0.2, 0), {}),
    "brokkoli": (("Brokkoli", 34, 3.6, 0.2, 2.7, 3, 2, 0.05), {"Stück": 400}),
    "rapsoel": (("Rapsöl", 900, 0, 100, 0, 0, 0, 0), {"EL": 10, "TL": 4}),
    "olivenoel": (("Olivenöl", 900, 0, 100, 0, 0, 0, 0), {"EL": 10, "TL": 4}),
    "sojasauce": (("Sojasauce", 60, 8, 0.1, 6, 0, 1, 15), {"EL": 16, "TL": 6}),
    "knoblauch": (("Knoblauch", 140, 6, 0.1, 28, 2, 1, 0), {"Zehe": 4}),
    "rote_linsen": (("Rote Linsen, getrocknet", 340, 24, 1.5, 50, 11, 2, 0.05), {}),
    "vollkornspaghetti": (("Vollkornspaghetti, roh", 350, 14, 2.5, 64, 9, 3, 0), {}),
    "passierte_tomaten": (("Passierte Tomaten", 33, 1.5, 0.2, 5, 1.5, 4.5, 0.2), {"Packung": 500}),
    "zwiebel": (("Zwiebel", 28, 1.2, 0.2, 5, 1.8, 4, 0), {"Stück": 80}),
    "moehre": (("Möhre", 36, 0.9, 0.2, 7, 3.6, 5, 0.1), {"Stück": 80}),
    "parmesan": (("Parmesan", 390, 35, 28, 0, 0, 0, 1.6), {"EL": 6}),
    "ei": (("Hühnerei", 140, 12.5, 9.5, 0.7, 0, 0.7, 0.35), {"Stück": 58}),
    "vollkornbrot": (("Vollkornbrot", 220, 7.5, 1.5, 40, 8, 3, 1.1), {"Scheibe": 50}),
    "butter": (("Butter", 740, 0.7, 82, 0.6, 0, 0.6, 0), {"EL": 10, "TL": 5}),
    "lachs": (("Lachsfilet, roh", 200, 20, 13, 0, 0, 0, 0.1), {"Stück": 125}),
    "kartoffeln": (("Kartoffeln, roh", 72, 2, 0.1, 15, 2, 0.8, 0), {"Stück": 100}),
    "spinat": (("Blattspinat", 23, 2.5, 0.4, 0.6, 2.6, 0.4, 0.15), {}),
    "kochsahne": (("Kochsahne 15 %", 160, 3, 15, 4, 0, 4, 0.1), {"EL": 15}),
    "banane": (("Banane", 93, 1.1, 0.2, 20, 2, 17, 0), {"Stück": 120}),
    "milch": (("Milch 1,5 %", 47, 3.4, 1.5, 4.8, 0, 4.8, 0.1), {"ml": 1.03}),
    "apfel": (("Apfel", 54, 0.3, 0.2, 12, 2.3, 10, 0), {"Stück": 150}),
    "mandeln": (("Mandeln", 600, 24, 52, 4, 12, 4, 0), {"Handvoll": 25}),
    "tofu": (("Tofu natur", 150, 15, 8.5, 2, 0.5, 0.5, 0), {"Packung": 200}),
    "kichererbsen": (("Kichererbsen, abgetropft", 120, 7, 2.5, 16, 6, 0.5, 0.5), {"Dose": 240}),
    "thunfisch": (("Thunfisch im eigenen Saft", 110, 25, 1, 0, 0, 0, 0.9), {"Dose": 150}),
    "paprika": (("Paprika, rot", 37, 1, 0.5, 6, 3.6, 6, 0), {"Stück": 160}),
    "gurke": (("Salatgurke", 15, 0.6, 0.2, 2, 0.5, 2, 0), {"Stück": 400}),
}

# slug: (Titel, Portionen, Kategorie, [(Lebensmittel, Menge, Einheit, optional)])
RECIPES: dict[str, tuple[str, float, str, list[tuple[str, float, str, bool]]]] = {
    "skyr_bowl": (
        "Skyr-Bowl mit Heidelbeeren",
        1,
        "Frühstück",
        [
            ("skyr", 250, "g", False),
            ("heidelbeeren", 100, "g", False),
            ("haferflocken", 3, "EL", False),
            ("honig", 1, "TL", False),
        ],
    ),
    "protein_pancakes": (
        "Protein-Pancakes mit Banane",
        2,
        "Frühstück",
        [
            ("haferflocken", 80, "g", False),
            ("ei", 2, "Stück", False),
            ("magerquark", 1, "Becher", False),
            ("banane", 1, "Stück", False),
            ("rapsoel", 1, "TL", False),
        ],
    ),
    "ruehrei_brot": (
        "Rührei mit Vollkornbrot",
        1,
        "Frühstück",
        [
            ("ei", 3, "Stück", False),
            ("vollkornbrot", 2, "Scheibe", False),
            ("butter", 1, "TL", False),
            ("paprika", 0.5, "Stück", True),
        ],
    ),
    "haehnchen_reis": (
        "Hähnchen-Reis-Pfanne mit Brokkoli",
        2,
        "Hauptgericht",
        [
            ("haehnchenbrust", 400, "g", False),
            ("reis", 150, "g", False),
            ("brokkoli", 300, "g", False),
            ("rapsoel", 1, "EL", False),
            ("sojasauce", 2, "EL", False),
            ("knoblauch", 1, "Zehe", False),
        ],
    ),
    "linsen_bolognese": (
        "Linsen-Bolognese mit Vollkornspaghetti",
        4,
        "Hauptgericht",
        [
            ("rote_linsen", 200, "g", False),
            ("vollkornspaghetti", 400, "g", False),
            ("passierte_tomaten", 1, "Packung", False),
            ("zwiebel", 1, "Stück", False),
            ("moehre", 2, "Stück", False),
            ("olivenoel", 1, "EL", False),
            ("parmesan", 40, "g", True),
        ],
    ),
    "lachs_kartoffeln": (
        "Lachs mit Kartoffeln und Rahmspinat",
        2,
        "Hauptgericht",
        [
            ("lachs", 2, "Stück", False),
            ("kartoffeln", 500, "g", False),
            ("spinat", 300, "g", False),
            ("kochsahne", 100, "g", False),
            ("knoblauch", 1, "Zehe", False),
        ],
    ),
    "kichererbsen_salat": (
        "Kichererbsen-Thunfisch-Salat",
        2,
        "Salat",
        [
            ("kichererbsen", 1, "Dose", False),
            ("thunfisch", 1, "Dose", False),
            ("gurke", 0.5, "Stück", False),
            ("paprika", 1, "Stück", False),
            ("olivenoel", 1, "EL", False),
        ],
    ),
    "tofu_pfanne": (
        "Tofu-Gemüse-Pfanne",
        2,
        "Hauptgericht",
        [
            ("tofu", 1, "Packung", False),
            ("paprika", 1, "Stück", False),
            ("brokkoli", 250, "g", False),
            ("reis", 120, "g", False),
            ("sojasauce", 2, "EL", False),
            ("rapsoel", 1, "EL", False),
            ("mandeln", 1, "Handvoll", True),
        ],
    ),
}

# slug: Kochschritte, ein Schritt pro Zeile
STEPS: dict[str, str] = {
    "haehnchen_reis": """Reis nach Packungsangabe garen.
Hähnchen in Streifen schneiden, Brokkoli in kleine Röschen teilen, Knoblauch fein hacken.
Öl in einer Pfanne erhitzen, Hähnchen 5–6 Minuten rundum anbraten.
Brokkoli und Knoblauch zugeben, 4 Minuten mitbraten, dabei 2–3 EL Wasser angießen.
Mit Sojasauce ablöschen, Reis unterheben und kurz durchschwenken.""",
    "linsen_bolognese": """Zwiebel und Möhren fein würfeln.
Olivenöl im Topf erhitzen, Zwiebel und Möhren 5 Minuten andünsten.
Rote Linsen und passierte Tomaten zugeben, mit 300 ml Wasser aufgießen.
Offen 15 Minuten köcheln lassen, bis die Linsen weich sind; mit Salz und Pfeffer abschmecken.
Spaghetti nach Packungsangabe kochen und mit der Sauce servieren, nach Wunsch mit Parmesan.""",
    "protein_pancakes": """Haferflocken fein mahlen.
Eier, Magerquark und die zerdrückte Banane mit den Haferflocken zu einem dicken Teig verrühren.
5 Minuten quellen lassen.
Pfanne mit wenig Öl erhitzen, je 2 EL Teig hineingeben und von jeder Seite 2 Minuten backen.""",
}


def seed_foods(session: Session) -> dict[str, Food]:
    foods: dict[str, Food] = {}
    for slug, (values, units) in FOODS.items():
        source_id = f"{DEMO_PREFIX}{slug}"
        food = find_by_source(session, FoodSource.CUSTOM, source_id)
        if food is None:
            name, kcal, protein, fat, carbs, fiber, sugar, salt = values
            data = FoodInput(name, kcal, protein, fat, carbs, fiber, sugar, salt)
            food = create_food(session, data, FoodSource.CUSTOM, source_id)
        for unit_name, grams in units.items():
            set_unit(session, food, unit_name, grams)
        foods[slug] = food
    return foods


def seed_recipes(session: Session, foods: dict[str, Food]) -> int:
    created = 0
    for slug, (title, servings, category, ingredients) in RECIPES.items():
        source_id = f"{DEMO_PREFIX}{slug}"
        existing = session.scalar(select(Recipe).where(Recipe.source_id == source_id))
        if existing is not None:
            if not existing.instructions:
                existing.instructions = STEPS.get(slug)
            continue
        recipe = create_recipe(
            session, RecipeInput(title, servings, category, instructions=STEPS.get(slug))
        )
        recipe.source = DEMO_SOURCE
        recipe.source_id = source_id
        for food_slug, quantity, unit, optional in ingredients:
            data = IngredientInput(foods[food_slug].id, quantity, unit, optional)
            add_ingredient(session, recipe, data)
        created += 1
    return created


def main() -> None:
    settings = get_settings()
    upgrade_to_head(settings)
    engine = create_db_engine(settings)
    with create_session_factory(engine)() as session:
        foods = seed_foods(session)
        created = seed_recipes(session, foods)
        session.commit()
    engine.dispose()
    print(f"Demo-Set: {len(foods)} Lebensmittel, {created} neue Rezepte.")


if __name__ == "__main__":
    main()
