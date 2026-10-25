"""Cookidoo-Sammlung → Rezeptentwürfe mit Zutatenzeilen für den Import in Tellerplan.

Läuft am Rechner, nicht im Add-on (nur Standardbibliothek):

    python tools/cookidoo_fetch.py dev/cookidoo/cookidoo_fuerth_naehrwerte.json \\
        dev/cookidoo/cookidoo_fuerth_entwuerfe.json

Liest die Sammlung (ID, Titel, Kategorie, Portionen, URL …), lädt je Rezept die
öffentliche Rezeptseite und übernimmt aus deren strukturierten Daten (JSON-LD,
schema.org/Recipe) nur die Zutatenzeilen. Gedrosselt (eine Seite alle paar
Sekunden) und mit Zwischenspeicher in `dev/cookidoo/pages/`, damit ein zweiter
Lauf nichts erneut abruft. Nur für die eigene, private Sammlung gedacht.

Nach Regel 2 liefern Entwürfe keine Nährwerte. Die Werte aus der Sammlung gehen
nur als `reference` mit, damit Tellerplan beim Zuordnen vergleichen kann; in die
Rechnung fließen sie nie ein.
"""

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FORMAT = "tellerplan-recipes"
FORMAT_VERSION = 1
SOURCE = "cookidoo"
USER_AGENT = "Mozilla/5.0 (Tellerplan, privater Import der eigenen Sammlung)"
DEFAULT_DELAY_SECONDS = 3.0
TIMEOUT_SECONDS = 20
JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
LEADING_NUMBER = re.compile(r"^\s*(\d+(?:[.,]\d+)?)")


def fetch_page(url: str, cache: Path, delay: float) -> str:
    """Rezeptseite aus dem Zwischenspeicher oder gedrosselt aus dem Netz."""
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    time.sleep(delay)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        page = response.read().decode("utf-8")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(page, encoding="utf-8")
    return page


def recipe_data(page: str) -> dict:
    """Das schema.org/Recipe-Objekt aus den JSON-LD-Blöcken der Seite."""
    for block in JSON_LD_PATTERN.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Recipe":
                return item
    raise ValueError("Keine strukturierten Rezeptdaten (schema.org/Recipe) gefunden")


def clean_line(line: str) -> str:
    """HTML-Entitäten auflösen („&frac12;“ → „½“), Leerraum vereinheitlichen."""
    return " ".join(html.unescape(line).split())


def servings_from(collection_value: str, recipe_yield: object) -> float | None:
    """Portionen aus der Sammlung („4“, „12 Stück“), sonst aus „recipeYield“ der Seite."""
    for text in (collection_value, recipe_yield if isinstance(recipe_yield, str) else ""):
        match = LEADING_NUMBER.match(text or "")
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def draft(entry: dict, page: str) -> dict:
    """Ein Rezeptentwurf im Importformat von Tellerplan."""
    data = recipe_data(page)
    ingredients = [clean_line(line) for line in data.get("recipeIngredient", [])]
    return {
        "source_id": entry["ID"],
        "title": entry["Titel"],
        "servings": servings_from(entry.get("Portionen", ""), data.get("recipeYield")),
        "yield_text": clean_line(str(data.get("recipeYield", ""))),
        "category": entry.get("Kategorie") or None,
        "source_url": entry["URL"],
        "total_time": entry.get("Gesamtzeit") or None,
        "note": entry.get("Hinweis") or None,
        "ingredients": [line for line in ingredients if line],
        "reference": {
            "kcal_per_serving": entry.get("kcal_pro_Portion"),
            "protein_g_per_serving": entry.get("Eiweiss_g"),
            "fat_g_per_serving": entry.get("Fett_g"),
            "carbs_g_per_serving": entry.get("KH_g"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("collection", type=Path, help="Sammlung als JSON (aus dem Widget)")
    parser.add_argument("output", type=Path, help="Zieldatei für die Entwürfe")
    parser.add_argument("--cache", type=Path, help="Ordner für geladene Seiten")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--limit", type=int, help="nur die ersten N Rezepte (zum Testen)")
    args = parser.parse_args()

    collection = json.loads(args.collection.read_text(encoding="utf-8"))[: args.limit]
    cache_dir = args.cache or args.collection.parent / "pages"
    drafts, failures = [], []
    for number, entry in enumerate(collection, start=1):
        try:
            page = fetch_page(entry["URL"], cache_dir / f"{entry['ID']}.html", args.delay)
            drafts.append(draft(entry, page))
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            failures.append(f"{entry['ID']} {entry['Titel']}: {error}")
        print(f"\r{number}/{len(collection)}", end="", flush=True)
    print()

    document = {"format": FORMAT, "version": FORMAT_VERSION, "source": SOURCE, "recipes": drafts}
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = sum(len(d["ingredients"]) for d in drafts)
    print(f"{len(drafts)} Entwürfe mit {lines} Zutatenzeilen nach {args.output}")
    for failure in failures:
        print(f"Fehler: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
