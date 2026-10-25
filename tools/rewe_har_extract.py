#!/usr/bin/env python3
"""
rewe_har_extract.py
Liest aus einem Firefox-HAR-Mitschnitt nur, was Tellerplan braucht – mit fester Feldliste.

Läuft am Rechner, nicht im Add-on (nur Standardbibliothek):

    python tools/rewe_har_extract.py "dev/Rewe/<mitschnitt>.har" [zielordner]

Ohne Datei nimmt es die neueste .har in dev/Rewe/. Ziel ist standardmäßig
dev/Rewe/rewe_json/ neben der HAR-Datei; danach tools/rewe_fetch.py ausführen.

Erkennt die Antworten an ihrem Inhalt (nicht an der URL), funktioniert daher auch mit
von Hand gekürzten, nicht mehr gültigen HAR-Dateien:

- Favoriten (/shop/api/favorites)  → rewe_favoriten.json   (einmal, je Produkt-ID)
- Bestellungen (Bestellseite)      → rewe_bestellungen.json (nur Titel, EAN, Menge, Kategorie)
- Produktseiten (im Browser offen) → ../pages/<produkt-id>.html (für tools/rewe_fetch.py)

Bewusst weggelassen: Preise, Kennungen von Listen und Bestellungen, Telefonnummer,
Kommentare, Adressen, Zeiten, Header, Cookies. Ein Selbsttest bricht ab, falls
dennoch etwas davon in den Ausgaben landet.

Achtung: Die HAR-Datei selbst enthält Cookies und Bestelldaten (u. a. Telefonnummer).
Nach dem Extrahieren löschen, nie weitergeben.
"""

import base64
import html
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Zentrale Parameter
# ---------------------------------------------------------------------------
DEFAULT_HAR_DIR = Path(__file__).resolve().parent.parent / "dev" / "Rewe"
DEFAULT_OUT_DIR = "rewe_json"
PAGES_DIR = Path("..") / "pages"  # relativ zum Zielordner
FAVORITES_FILE = "rewe_favoriten.json"
ORDERS_FILE = "rewe_bestellungen.json"
SHOP_URL = "https://www.rewe.de/shop"
# Bestellpositionen ohne Ware
SKIPPED_LINE_TYPES = {"REFUND", "TIMESLOT"}
# Was in keiner Ausgabe vorkommen darf (Selbsttest)
FORBIDDEN_KEYS = re.compile(r"phone|comment|email|address|street|zip|csId|payback|iban", re.I)
PHONE_LIKE = re.compile(r"\b(?:\+49|0)\d{9,13}\b")
# ---------------------------------------------------------------------------

TEXT_FIELD = re.compile(r'"text"\s*:\s*"')
PRODUCT_LINK = re.compile(r"/shop/products/(\d+)")
JSON_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)


def responses(raw: str) -> list[tuple[str | None, str]]:
    """Alle Antworten als (URL, Text) – auch wenn die HAR-Datei kein gültiges JSON mehr ist.

    In gekürzten Dateien fehlt die URL oft; dann ist sie None.
    """
    try:
        entries = json.loads(raw).get("log", {}).get("entries", [])
    except json.JSONDecodeError:
        entries = None
    if entries is not None:
        found = []
        for entry in entries:
            content = entry.get("response", {}).get("content", {})
            text = content.get("text")
            if text and content.get("encoding") == "base64":
                text = base64.b64decode(text).decode("utf-8", errors="replace")
            if text:
                found.append((entry.get("request", {}).get("url"), text))
        return found
    decoder = json.JSONDecoder()
    found = []
    for match in TEXT_FIELD.finditer(raw):
        try:
            text, _ = decoder.raw_decode(raw, match.end() - 1)
        except json.JSONDecodeError:
            continue
        if isinstance(text, str):
            found.append((None, text))
    return found


# --- Favoriten -------------------------------------------------------------


def _grammage(item: dict) -> str | None:
    """Packungsgröße ohne Grundpreis: „200g (1 kg = 19,95 €)“ → „200g“."""
    text = item.get("priceInformation", {}).get("grammage")
    return text.split(" (")[0].strip() if text else None


def favorite_products(texts: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for text in texts:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        first = data[0] if isinstance(data, list) and data else None
        if not (isinstance(first, dict) and "items" in first):
            continue
        for favorite_list in data:
            for item in favorite_list.get("items", []):
                if item.get("type") != "product" or item.get("productId") in seen:
                    continue
                seen[item["productId"]] = {
                    "product_id": item["productId"],
                    "article_id": item.get("articleId"),
                    "name": item.get("productName"),
                    "grammage": _grammage(item),
                    "url": f"{SHOP_URL}{item.get('productUrl', '')}",
                    "bio": bool(item.get("bio")),
                    "regional": bool(item.get("regional")),
                }
    return sorted(seen.values(), key=lambda p: (p["name"] or "").casefold())


# --- Bestellungen ----------------------------------------------------------


def _orders_in_page(page: str) -> list[dict]:
    """Bestellobjekte (mit „lineItems“), die als maskiertes JSON in der Bestellseite stecken."""
    source = html.unescape(page)
    decoder = json.JSONDecoder()
    orders, position = [], 0
    while (i := source.find('"lineItems"', position)) >= 0:
        position = i + 1
        for start in range(i, max(0, i - 200_000), -1):
            if source[start] != "{":
                continue
            try:
                obj, end = decoder.raw_decode(source, start)
            except json.JSONDecodeError:
                continue
            if end > i and isinstance(obj, dict) and "lineItems" in obj:
                orders.append(obj)
                position = end
                break
    return orders


def order_lines(texts: list[str]) -> list[dict]:
    lines = []
    seen_orders: set[str] = set()  # dieselbe Bestellung steckt oft doppelt in der Seite
    orders = []
    for text in texts:
        if "lineItems" not in text:
            continue
        for order in _orders_in_page(text):
            key = str(order.get("id")) if order.get("id") else json.dumps(order.get("lineItems"))
            if key not in seen_orders:
                seen_orders.add(key)
                orders.append(order)
    for order_number, order in enumerate(orders, start=1):
        for item in order.get("lineItems", []):
            if item.get("lineItemType") in SKIPPED_LINE_TYPES:
                continue
            lines.append(
                {
                    "order": order_number,
                    "title": item.get("title"),
                    "ean": item.get("ean") or None,
                    "quantity": item.get("actualQuantity") or item.get("quantity"),
                    "unit": item.get("volumeCode"),
                    "category": (item.get("category") or {}).get("name"),
                    "type": item.get("lineItemType"),
                }
            )
    return lines


# --- Produktseiten ----------------------------------------------------------


def _sku(page: str) -> str | None:
    """Artikelnummer aus dem JSON-LD der Seite (entspricht variantArticleId im Link)."""
    for block in JSON_LD.findall(page):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product" and data.get("sku"):
            return str(data["sku"])
    return None


def product_pages(found: list[tuple[str | None, str]]) -> dict[str, str]:
    """Im Browser geöffnete Produktseiten mit Nährwerttabelle.

    Schlüssel ist die Produkt-ID aus der URL der Anfrage; fehlt die URL (gekürzte
    HAR-Datei), „sku-<Artikelnummer>“ aus dem JSON-LD.
    """
    pages = {}
    for url, text in found:
        if '"nutritionFacts"' not in text or "schema.org" not in text:
            continue
        match = PRODUCT_LINK.search(url or "")
        sku = _sku(text)
        if match:
            pages[match.group(1)] = text
        elif sku:
            pages[f"sku-{sku}"] = text
    return pages


# --- Ausgabe ---------------------------------------------------------------


def self_check(path: Path) -> None:
    """Bricht ab, wenn eine Ausgabe doch persönliche Felder oder Telefonnummern enthält."""
    text = path.read_text(encoding="utf-8")
    keys = {k for k in re.findall(r'"([A-Za-z_]+)"\s*:', text) if FORBIDDEN_KEYS.search(k)}
    if keys or PHONE_LIKE.search(text):
        path.unlink()
        found = sorted(keys) or "Telefonmuster"
        sys.exit(f"Selbsttest fehlgeschlagen für {path.name} ({found}) – Datei gelöscht.")


def write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8")
    self_check(path)


def find_har() -> Path:
    """Ohne Argument: neueste .har in dev/Rewe/."""
    hars = sorted(DEFAULT_HAR_DIR.glob("*.har"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not hars:
        sys.exit("Keine HAR-Datei gefunden. Nutzung: rewe_har_extract.py <datei.har> [zielordner]")
    print(f"Verwende HAR: {hars[0].name}")
    return hars[0]


def main() -> None:
    har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_har()
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else har_path.parent / DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    found = responses(har_path.read_text(encoding="utf-8"))
    texts = [text for _, text in found]
    print(f"{len(texts)} Antwort(en) im Mitschnitt")

    favorites = favorite_products(texts)
    if favorites:
        document = {"format": "rewe-favorites", "version": 1, "products": favorites}
        write_json(out_dir / FAVORITES_FILE, document)
        print(f"Favoriten: {len(favorites)} Produkte → {FAVORITES_FILE}")

    lines = order_lines(texts)
    if lines:
        write_json(out_dir / ORDERS_FILE, {"format": "rewe-orders", "version": 1, "lines": lines})
        print(f"Bestellungen: {len(lines)} Positionen → {ORDERS_FILE}")

    pages = product_pages(found)
    pages_dir = (out_dir / PAGES_DIR).resolve()
    pages_dir.mkdir(parents=True, exist_ok=True)
    for product_id, page in pages.items():
        (pages_dir / f"{product_id}.html").write_text(page, encoding="utf-8")
    if pages:
        print(f"Produktseiten: {len(pages)} → {pages_dir}")

    print("Hinweis: Die HAR-Datei enthält Cookies und Bestelldaten – nach dem Extrahieren löschen.")


if __name__ == "__main__":
    main()
