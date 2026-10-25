"""REWE-Favoriten → Lebensmittel mit Nährwerten für den Import in Tellerplan.

Läuft am Rechner, nicht im Add-on (nur Standardbibliothek):

    python tools/rewe_fetch.py dev/Rewe/rewe_json/rewe_favoriten.json \\
        dev/Rewe/rewe_lebensmittel.json

Fragt selbst nichts bei REWE an (automatisierte Abrufe lehnt REWE ab). Quellen je Produkt:

1. Produktseite aus dem Zwischenspeicher `dev/Rewe/pages/<produkt-id>.html` – entsteht,
   wenn man die Seite im Browser öffnet, während der HAR-Mitschnitt läuft, und danach
   `tools/rewe_har_extract.py` ausführt. Übernommen werden Name, Hersteller,
   Barcode (JSON-LD) und die Nährwerttabelle (GS1-Codes, je 100 g/ml).
2. Sonst, wenn der Barcode bekannt ist: Open Food Facts (offene Daten, Abfrage erlaubt;
   Antworten werden in `dev/Rewe/off/` zwischengespeichert).
3. Sonst steht das Produkt in der Linkliste `<ausgabe>_offen.html`/`.json`: Diese Seiten
   im Browser öffnen (HAR-Mitschnitt läuft), extrahieren, dieses Skript erneut starten.

Produkte ohne Nährwerttabelle (Drogerie, loses Obst und Gemüse) stehen mit Grund unter
`skipped`; für Grundzutaten wie Apfel ist BLS die bessere Quelle.
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

FORMAT = "tellerplan-foods"
FORMAT_VERSION = 1
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_FIELDS = "product_name,product_name_de,brands,quantity,nutriments"
OFF_USER_AGENT = "Tellerplan/0.3 (privater Abgleich eigener Einkaufsfavoriten)"
# Open Food Facts drosselt (429); lieber langsam, nach 429 die verlangte Pause einhalten
OFF_DELAY_SECONDS = 6.0
OFF_RETRY_AFTER_SECONDS = 60
TOO_MANY_REQUESTS = 429
TIMEOUT_SECONDS = 20
KJ_PER_KCAL = 4.184
PER_100 = 100.0

JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
NUTRITION_MARKER = '"nutritionFacts":'
BARCODE_PATTERN = re.compile(r"\d{8}|\d{12,14}")
# GS1-Nährstoffcode → Feld in Tellerplan (Energie gesondert, kcal oder kJ)
NUTRIENT_CODES = {
    "PRO-": "protein_g",
    "FAT": "fat_g",
    "CHOAVL": "carbs_g",
    "SUGAR-": "sugar_g",
    "SALTEQ": "salt_g",
    "FIBTG": "fiber_g",
}
# Open-Food-Facts-Feld (je 100 g) → Feld in Tellerplan
OFF_NUTRIENTS = {
    "energy-kcal_100g": "kcal",
    "proteins_100g": "protein_g",
    "fat_100g": "fat_g",
    "carbohydrates_100g": "carbs_g",
    "sugars_100g": "sugar_g",
    "salt_100g": "salt_g",
    "fiber_100g": "fiber_g",
}
REQUIRED = ("kcal", "protein_g", "fat_g", "carbs_g")


# --- Hilfen ----------------------------------------------------------------


def valid_barcode(code: str | None) -> str | None:
    """EAN/GTIN mit gültiger Prüfziffer, sonst None (REWE nutzt teils interne Nummern)."""
    if not code or not BARCODE_PATTERN.fullmatch(code):
        return None
    digits = [int(c) for c in reversed(code)]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[1:], start=1))
    return code if (10 - total % 10) % 10 == digits[0] else None


def product_barcode(product: dict) -> str | None:
    """Barcode aus der Artikel-ID oder aus „variantArticleId“ im Produktlink."""
    variant = product.get("url", "").partition("variantArticleId=")[2].split("&")[0]
    return valid_barcode(product.get("article_id")) or valid_barcode(variant or None)


def _rounded(values: dict[str, float]) -> dict[str, float]:
    return {key: round(value, 2) for key, value in values.items()}


def _missing(values: dict[str, float]) -> list[str]:
    return [key for key in REQUIRED if key not in values]


# --- REWE-Produktseite (aus dem Zwischenspeicher) --------------------------


def product_data(page: str) -> dict:
    """Das schema.org/Product-Objekt (Name, Barcode, Hersteller) der Seite."""
    for block in JSON_LD_PATTERN.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


def nutrition_facts(page: str) -> list[dict]:
    """Die eingebettete Nährwerttabelle; leer, wenn die Seite keine hat."""
    start = page.find(NUTRITION_MARKER)
    if start < 0:
        return []
    try:
        facts, _ = json.JSONDecoder().raw_decode(page, start + len(NUTRITION_MARKER))
    except ValueError:
        return []
    return facts if isinstance(facts, list) else []


def nutrients_per_100(facts: list[dict]) -> tuple[dict[str, float], str] | None:
    """Nährwerte je 100 g bzw. 100 ml (Zustand „unzubereitet“ bevorzugt) und die Bezugseinheit."""
    if not facts:
        return None
    unprepared = [f for f in facts if f.get("preparationState", {}).get("code") == "UNPREPARED"]
    fact = (unprepared or facts)[0]
    serving = fact.get("servingSize") or {}
    factor = PER_100 / (serving.get("value") or PER_100)
    values: dict[str, float] = {}
    kilojoules = None
    for nutrient in fact.get("nutrientInformation", []):
        code = nutrient.get("nutrientType", {}).get("code")
        amount = nutrient.get("quantityContained", {})
        value = amount.get("value")
        if not isinstance(value, int | float):
            continue
        if code == "ENER-" and amount.get("uomShortText") == "kcal":
            values["kcal"] = value * factor
        elif code == "ENER-" and amount.get("uomShortText") == "kJ":
            kilojoules = value * factor
        elif code in NUTRIENT_CODES:
            values[NUTRIENT_CODES[code]] = value * factor
    if "kcal" not in values and kilojoules is not None:
        values["kcal"] = kilojoules / KJ_PER_KCAL
    return _rounded(values), f"100 {serving.get('uomShortText') or 'g'}"


def from_rewe_page(product: dict, page: str) -> tuple[dict | None, str | None]:
    """Lebensmittel aus einer gespeicherten REWE-Produktseite oder (None, Grund)."""
    data = product_data(page)
    result = nutrients_per_100(nutrition_facts(page))
    if result is None:
        return None, "keine Nährwerttabelle auf der Produktseite"
    values, basis = result
    if missing := _missing(values):
        return None, f"Nährwerte unvollständig ({', '.join(missing)})"
    brand = data.get("brand")
    barcode = valid_barcode(data.get("gtin13") or data.get("gtin")) or product_barcode(product)
    entry = {
        "source": "rewe",
        "source_id": barcode or f"rewe-{product['product_id']}",
        "barcode": barcode,
        "name": html.unescape(data.get("name") or product["name"]),
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "package": product.get("grammage"),
        "basis": basis,
        "url": product["url"],
        **values,
    }
    return entry, None


# --- Open Food Facts --------------------------------------------------------


def fetch_off(barcode: str, cache_dir: Path) -> dict | None:
    """Produkt von Open Food Facts (zwischengespeichert); None, wenn dort unbekannt."""
    cache = cache_dir / f"{barcode}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data = _request_off(barcode)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data.get("product") if data.get("status") == 1 else None


def _request_off(barcode: str, retry: bool = True) -> dict:
    time.sleep(OFF_DELAY_SECONDS)
    url = f"{OFF_URL.format(barcode=barcode)}?fields={OFF_FIELDS}"
    request = Request(url, headers={"User-Agent": OFF_USER_AGENT})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except HTTPError as error:
        if error.code == 404:
            return {"status": 0}
        if error.code == TOO_MANY_REQUESTS and retry:
            wait = int(error.headers.get("Retry-After") or OFF_RETRY_AFTER_SECONDS)
            print(f"\nOpen Food Facts bittet um eine Pause, warte {wait} s …")
            time.sleep(wait)
            return _request_off(barcode, retry=False)
        raise


def from_off(product: dict, barcode: str, off: dict) -> tuple[dict | None, str | None]:
    """Lebensmittel aus Open Food Facts oder (None, Grund)."""
    nutriments = off.get("nutriments") or {}
    values = {
        field: float(nutriments[key])
        for key, field in OFF_NUTRIENTS.items()
        if isinstance(nutriments.get(key), int | float)
    }
    if "kcal" not in values and isinstance(nutriments.get("energy_100g"), int | float):
        values["kcal"] = nutriments["energy_100g"] / KJ_PER_KCAL
    if missing := _missing(values):
        return None, f"Open Food Facts ohne vollständige Nährwerte ({', '.join(missing)})"
    brand = (off.get("brands") or "").split(",")[0].strip() or None
    entry = {
        "source": "off",
        "source_id": barcode,
        "barcode": barcode,
        "name": product["name"],
        "brand": brand,
        "package": product.get("grammage") or off.get("quantity"),
        "basis": "100 g",
        "url": product["url"],
        **_rounded(values),
    }
    return entry, None


# --- Linkliste --------------------------------------------------------------


def write_open_list(path: Path, products: list[dict]) -> None:
    """Noch offene Produkte als JSON und als HTML-Seite mit Links zum Abarbeiten."""
    links = [{"name": p["name"], "package": p.get("grammage"), "url": p["url"]} for p in products]
    path.with_suffix(".json").write_text(
        json.dumps({"products": links}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # Links öffnen im selben Tab: Das Netzwerkprotokoll zeichnet nur den Tab auf, in dem es läuft.
    rows = "\n".join(
        f'<li><a href="{html.escape(p["url"])}">'
        f"{html.escape(p['name'] or '?')}</a> <small>{html.escape(p['package'] or '')}</small></li>"
        for p in links
    )
    path.with_suffix(".html").write_text(
        f"""<!doctype html><html lang="de"><meta charset="utf-8">
<title>REWE – offene Produkte ({len(links)})</title>
<style>body{{font-family:system-ui;max-width:760px;margin:2em auto;line-height:1.6}}
a:visited{{color:#888}}</style>
<h1>Noch offen: {len(links)} Produkte</h1>
<ol style="line-height:1.4">
<li>Diese Seite in Firefox öffnen, F12 → Reiter „Netzwerkanalyse“.</li>
<li>Im Zahnrad-Menü der Netzwerkanalyse „Logs beibehalten“ einschalten – sonst löscht
Firefox das Protokoll bei jedem Seitenwechsel.</li>
<li>Links in diesem Tab anklicken, mit Alt+← zurück (besuchte werden grau).</li>
<li>Rechtsklick in die Liste der Anfragen → „Alle als HAR speichern“, Datei nach
<code>dev/Rewe/</code>.</li>
<li><code>python tools/rewe_har_extract.py</code>,
dann <code>python tools/rewe_fetch.py</code>.</li>
</ol>
<p>Nicht alle Produkte nötig: Am meisten bringen die, die als Standard hinter einer
Grundzutat stehen sollen (z. B. Milch, Joghurt, Käse). Drogerieartikel überspringen.</p>
<ol>
{rows}
</ol></html>
""",
        encoding="utf-8",
    )


# --- Ablauf -----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("favorites", type=Path, help="Favoriten aus tools/rewe_har_extract.py")
    parser.add_argument("output", type=Path, help="Zieldatei für die Lebensmittel")
    parser.add_argument("--pages", type=Path, help="Ordner mit gespeicherten Produktseiten")
    parser.add_argument("--no-off", action="store_true", help="Open Food Facts nicht fragen")
    args = parser.parse_args()

    rewe_dir = args.favorites.resolve().parent.parent
    pages_dir = args.pages or rewe_dir / "pages"
    off_dir = rewe_dir / "off"
    products = json.loads(args.favorites.read_text(encoding="utf-8"))["products"]

    foods, skipped, still_open = [], [], []
    errors: list[str] = []
    for number, product in enumerate(products, start=1):
        page_file = pages_dir / f"{product['product_id']}.html"
        barcode = product_barcode(product)
        if page_file.exists():
            entry, reason = from_rewe_page(product, page_file.read_text(encoding="utf-8"))
        elif barcode and not args.no_off:
            try:
                off = fetch_off(barcode, off_dir)
            except (HTTPError, URLError, TimeoutError) as error:
                off = None
                errors.append(f"{barcode} {product['name']}: {error}")
            entry, reason = from_off(product, barcode, off) if off else (None, None)
        else:
            entry, reason = None, None
        if entry is not None:
            foods.append(entry)
        elif reason and page_file.exists():
            skipped.append({"name": product["name"], "reason": reason})
        else:
            still_open.append(product)
        print(f"\r{number}/{len(products)}", end="", flush=True)
    print()

    document = {"format": FORMAT, "version": FORMAT_VERSION, "foods": foods, "skipped": skipped}
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    open_list = args.output.with_name(f"{args.output.stem}_offen")
    write_open_list(open_list, still_open)
    by_source = {s: sum(1 for f in foods if f["source"] == s) for s in ("rewe", "off")}
    print(
        f"{len(foods)} Lebensmittel nach {args.output} (REWE-Seiten {by_source['rewe']}, "
        f"Open Food Facts {by_source['off']}), {len(skipped)} übersprungen, "
        f"{len(still_open)} offen → {open_list.with_suffix('.html')}"
    )
    for error in errors:
        print(f"Open Food Facts nicht erreichbar (nächster Lauf versucht es erneut): {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
