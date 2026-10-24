"""Legt Demo-Rezepte auf Basis der BLS-Lebensmittel an (mehrfach ausführbar).

Aufruf in tellerplan/app:  python -m scripts.seed_demo

Voraussetzung: Die BLS-Lebensmittel sind eingespielt (Migration 0005). Das Skript
ergänzt bei den verwendeten BLS-Lebensmitteln gängige Einheiten (z. B. 1 Stück Ei)
und legt die Demo-Rezepte an. Rezepte tragen `source_id` mit dem Präfix „demo:“.

Ältere Demo-Lebensmittel mit Näherungswerten (source_id „demo:…“) werden durch die
BLS-Einträge ersetzt: Zutaten und Tagebucheinträge zeigen danach auf BLS, die
Demo-Lebensmittel werden gelöscht.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db import create_db_engine, create_session_factory
from migrate import upgrade_to_head
from modules.diary.models import DiaryEntry
from modules.foods.models import Food, FoodSource
from modules.foods.service import find_by_source, set_unit
from modules.recipes.models import Recipe, RecipeIngredient
from modules.recipes.service import (
    IngredientInput,
    RecipeInput,
    add_ingredient,
    create_recipe,
    describe_ingredient,
)
from settings import get_settings

DEMO_PREFIX = "demo:"
DEMO_SOURCE = "demo"

# slug: (BLS-Code, Einheiten in Gramm)
FOODS: dict[str, tuple[str, dict[str, float]]] = {
    "skyr": ("M710100", {"Becher": 450}),
    "magerquark": ("M713100", {"Becher": 250}),
    "huettenkaese": ("M711100", {"Becher": 200}),
    "heidelbeeren": ("F304100", {"Handvoll": 50}),
    "haferflocken": ("C133000", {"EL": 10}),
    "honig": ("S120000", {"TL": 7, "EL": 20}),
    "haehnchenbrust": ("V416100", {}),
    "reis": ("C352000", {}),
    "brokkoli": ("G312100", {"Stück": 400}),
    "rapsoel": ("Q180000", {"EL": 10, "TL": 4}),
    "olivenoel": ("Q120000", {"EL": 10, "TL": 4}),
    "sojasauce": ("R143000", {"EL": 16, "TL": 6}),
    "knoblauch": ("G490100", {"Zehe": 4}),
    "rote_linsen": ("H730000", {}),
    "vollkornspaghetti": ("E510000", {}),
    "passierte_tomaten": ("R161200", {"Packung": 500}),
    "zwiebel": ("G480100", {"Stück": 80}),
    "moehre": ("G620100", {"Stück": 80}),
    "parmesan": ("M306400", {"EL": 6}),
    "ei": ("E111100", {"Stück": 58}),
    "vollkornbrot": ("B101000", {"Scheibe": 50}),
    "butter": ("Q630000", {"EL": 10, "TL": 5}),
    "lachs": ("T410100", {"Stück": 125}),
    "kartoffeln": ("K110100", {"Stück": 100}),
    "spinat": ("G211100", {}),
    "kochsahne": ("M171500", {"EL": 15}),  # BLS kennt keine Kochsahne; Kaffeesahne 10 %
    "banane": ("F503100", {"Stück": 120}),
    "milch": ("M111200", {"ml": 1.03}),
    "apfel": ("F110100", {"Stück": 150}),
    "mandeln": ("H210100", {"Handvoll": 25}),
    "tofu": ("H861000", {"Packung": 200}),
    "kichererbsen": ("H720902", {"Dose": 240}),
    "thunfisch": ("T121902", {"Dose": 150}),
    "paprika": ("G543100", {"Stück": 160}),
    "gurke": ("G520100", {"Stück": 400}),
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
    """BLS-Lebensmittel der Demo-Rezepte holen und ihre Einheiten ergänzen."""
    foods: dict[str, Food] = {}
    for slug, (bls_code, units) in FOODS.items():
        food = find_by_source(session, FoodSource.BLS, bls_code)
        if food is None:
            raise SystemExit(f"BLS-Lebensmittel {bls_code} fehlt – Migration 0005 gelaufen?")
        for unit_name, grams in units.items():
            set_unit(session, food, unit_name, grams)
        foods[slug] = food
    return foods


def replace_demo_foods(session: Session, foods: dict[str, Food]) -> int:
    """Verweise von alten Demo-Lebensmitteln auf BLS umhängen, dann die alten löschen."""
    replaced = 0
    for slug, food in foods.items():
        old = find_by_source(session, FoodSource.CUSTOM, f"{DEMO_PREFIX}{slug}")
        if old is None:
            continue
        session.execute(
            update(RecipeIngredient)
            .where(RecipeIngredient.food_id == old.id)
            .values(food_id=food.id)
        )
        session.execute(
            update(DiaryEntry).where(DiaryEntry.food_id == old.id).values(food_id=food.id)
        )
        session.delete(old)
        replaced += 1
    session.flush()
    for ingredient in session.scalars(
        select(RecipeIngredient).where(
            RecipeIngredient.food_id.in_([food.id for food in foods.values()])
        )
    ):
        ingredient.raw_text = describe_ingredient(
            ingredient.quantity, ingredient.unit, ingredient.food.name
        )
    return replaced


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
        replaced = replace_demo_foods(session, foods)
        created = seed_recipes(session, foods)
        session.commit()
    engine.dispose()
    print(
        f"Demo-Set: {len(foods)} BLS-Lebensmittel mit Einheiten, {created} neue Rezepte, "
        f"{replaced} alte Demo-Lebensmittel ersetzt."
    )


if __name__ == "__main__":
    main()
