# Tellerplan – Architektur

Stand: 2026-10-24

## Ziel und Leitentscheidungen

Tellerplan ist eine selbst gehostete App, die Kalorienzählen und Rezeptverwaltung mit Wochenplan vereint: ein GitHub-Repo `tellerplan-ha`, ein Home-Assistant-Add-on mit Slug `tellerplan`, eine SQLite-Datenbank.

| Entscheidung | Festlegung | Begründung |
| --- | --- | --- |
| Repo-Schnitt | Ein Repo, eine App, innen nach Modulen getrennt | Rezepte, Plan und Tagebuch teilen dieselben Lebensmittel und Nährwerte |
| Maßgebliche Nährwerte | Immer aus der eigenen Lebensmitteldatenbank berechnet | Zutaten werden manuell präzisiert (z. B. welche Sahne) |
| Quell-Nährwerte | Werden beim Import **nicht** übernommen | Keine zweite Wahrheit, keine Abweichungen zu pflegen |
| Rolle des Imports | Liefert nur Titel, Portionen, Link und rohe Zutatenliste | Rezepte sind jederzeit editierbar und werden schrittweise gematcht |
| Portionen | Rezept hat Standardportionen; Plan kann sie ändern; Tagebuch zählt nur die gegessenen | Planung und Verzehr sind getrennte Fragen |
| Historie | Tagebucheinträge speichern einen Nährwert-Snapshot | Spätere Rezeptänderungen verändern keine vergangenen Tage |
| Cookidoo-Planung | Link zur Rezeptseite wird gespeichert, Planung dort per Link | Keine öffentliche Cookidoo-Schnittstelle zum Einplanen bekannt |

## Systemüberblick

Drei Zugänge, ein Add-on auf dem Home-Assistant-Pi, eine Datenbank; das Tagebuch ist der Kern, alles andere speist es.

```
┌──────────────────┐  ┌──────────────────────┐  ┌───────────────────────────┐
│ iPhone: PWA      │  │ iPhone: Kurzbefehle  │  │ Rechner: Skripte          │
│ Heute·Rezepte·   │  │ Cookidoo-Share →     │  │ Cookidoo-Sammlung,        │
│ Plan (HA-Leiste) │  │ Import, Gewicht      │  │ BLS-Import, Entwicklung   │
└────────┬─────────┘  └──────────┬───────────┘  └─────────────┬─────────────┘
         │ Ingress               │ HTTPS + Token              │ HTTPS + Token
┌────────▼───────────────────────▼─────────────────────────────▼────────────┐
│ Tellerplan · Home-Assistant-Add-on · FastAPI                               │
│  ┌────────────────────────────┐   ┌─────────────────────────────────────┐ │
│  │ web · Ingress              │   │ api/v1 · Port 8099                  │ │
│  │ Seiten, HTMX, Ranking-UI   │   │ JSON für UI, Kurzbefehle, Skripte   │ │
│  └─────────────┬──────────────┘   └──────────────────┬──────────────────┘ │
│        ┌───────┴─────────┬─────────────┬─────────────┴──┬─────────────┐   │
│  ┌─────▼─┐ ┌─────────┐ ┌─▼───────┐ ┌───▼──────┐ ┌───────▼─┐ ┌─────────▼┐  │
│  │ foods │ │nutrition│ │ recipes │ │importers │ │ planner │ │ diary ★  │  │
│  └───────┘ └─────────┘ └─────────┘ └──────────┘ └─────────┘ └──────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ SQLite · /data/app.db · SQLAlchemy + Alembic · in HA-Backups         │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

Die PWA läuft über Ingress ohne eigenes Login; Kurzbefehle und Rechner-Skripte sprechen die API auf Port 8099 mit Token an. Externe Daten (BLS, Open Food Facts, Rezeptseiten) kommen nur über `foods` und `importers` herein.

## Module und Verantwortlichkeiten

Sechs Fachmodule mit klaren Grenzen; nur `nutrition` rechnet Nährwerte, alle anderen fragen es.

| Modul | Verantwortung | Nutzt |
| --- | --- | --- |
| `foods` | Lebensmittel mit Nährwerten pro 100 g aus BLS 4.0, Open Food Facts und eigenen Einträgen; Suche; Einheiten pro Lebensmittel | – |
| `nutrition` | Menge + Einheit → Gramm → Nährwerte; Summen für Rezept, Portion, Tag | `foods` |
| `recipes` | Rezepte, Zutatenlisten, Zuordnung Zutat → Lebensmittel, Alias-Lernen, Matching-Status | `foods`, `nutrition` |
| `importers` | Quelle → Rezeptentwurf (Titel, Portionen, Link, rohe Zutatenzeilen); keine Nährwerte | `recipes` |
| `planner` | Wochenplan über 1–2 Wochen: Tag × Mahlzeit → Rezept mit geplanten Portionen | `recipes` |
| `diary` | Tagebuch mit vier Mahlzeiten, Tageslimit, Balken; Übernahme aus dem Plan mit gegessenen Portionen | `nutrition`, `planner` |

Querschnitt: `settings` (zentrale Parameter aus `options.json`), `api` (JSON für UI und Kurzbefehle), `web` (Seiten und UI-Komponenten).

## Datenmodell

Zehn Tabellen; Nährwerte existieren nur an `food`, alles andere verweist darauf oder hält einen Snapshot.

| Tabelle | Wichtige Felder | Regel |
| --- | --- | --- |
| `food` | Name, Quelle (bls / off / custom), Quell-ID, Nährwerte pro 100 g (kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz, weitere als JSON) | Einzige Stelle mit Nährwerten |
| `food_unit` | food_id, Einheit (EL, TL, Stück, Becher, Prise), Gramm | Umrechnung pro Lebensmittel; Dichte für ml |
| `recipe` | Titel, Quelle, `source_url`, Quell-ID, Standardportionen, Kategorie, Tags, Favorit, Notiz | Keine Nährwertfelder |
| `recipe_ingredient` | recipe_id, Reihenfolge, Originaltext, Menge, Einheit, food_id (leer = offen), Gramm, optional-Flag | Jede Zeile frei editierbar, auch nach dem Matching |
| `ingredient_alias` | normalisierter Zutatentext → food_id, Treffer-Anzahl | Wird bei jeder manuellen Zuordnung gelernt |
| `plan_entry` | Datum, Mahlzeit, recipe_id, geplante Portionen | Vorbelegt mit Standardportionen, im Plan änderbar |
| `diary_entry` | Datum, Mahlzeit, food_id oder recipe_id, Menge bzw. gegessene Portionen, plan_entry_id, Nährwert-Snapshot | Nur diese Einträge zählen für den Tag |
| `goal` | gültig ab, kcal-Limit, Eiweiß-, Fett-, KH-Ziel | Historisiert, damit alte Tage gegen das damalige Ziel laufen |
| `weight` | Datum, kg, Quelle (manuell / Health) | Später per Kurzbefehl |
| `import_job` | Quelle, Eingabe (URL/ID), Status, Fehlertext | Nachvollziehbarer Massenimport |

Abgeleitete Werte werden nicht gespeichert, sondern berechnet: Nährwerte pro Rezept und Portion, Matching-Grad eines Rezepts (z. B. 9 von 11 Zutaten zugeordnet) und Tagessummen. Ein Rezept mit offenen Zutaten lässt sich planen; beim Loggen erscheint ein Hinweis, dass der Wert unvollständig ist.

## Kernabläufe

Vier Abläufe tragen die App: Rezept anlegen, Zutaten zuordnen, planen, loggen.

**Rezept importieren**

1. Eingabe: URL, Cookidoo-ID, Kurzbefehl-Share oder eingefügter Text.
2. Importer erzeugt einen Entwurf: Titel, Standardportionen, Link, rohe Zutatenzeilen.
3. Parser zerlegt jede Zeile in Menge, Einheit und Zutat („200 g Sahne“ → 200 / g / Sahne).
4. Rezept wird gespeichert, auch wenn noch keine Zutat zugeordnet ist.

**Zutaten zuordnen (Matching)**

1. Alias-Tabelle prüfen: bekannte Zutat → Lebensmittel direkt setzen.
2. Sonst Volltextsuche in `food` mit Vorschlägen nach Ähnlichkeit.
3. Prüfansicht zeigt pro Zeile Vorschlag, Gramm und Status; du bestätigst, präzisierst („Sahne“ → „Schlagsahne 30 %“) oder legst ein eigenes Lebensmittel an.
4. Jede manuelle Wahl wird als Alias gelernt und hilft beim nächsten Rezept.
5. Einheiten ohne Grammangabe (EL, Stück) holen ihre Umrechnung aus `food_unit`; fehlt sie, fragt die Ansicht einmal nach.

**Planen**

1. In der Rezeptauswahl (Ranking) „Einplanen“ tippen.
2. Tag und Mahlzeit wählen; Portionen sind mit dem Rezeptstandard vorbelegt und änderbar.
3. Der Plan zeigt 1 oder 2 Wochen, je Tag die geplanten kcal und Eiweiß als Vorschau.
4. Cookidoo-Rezepte haben einen Button „In Cookidoo öffnen“, um sie dort einzuplanen.

**Loggen**

1. Das Tagebuch hat vier Bereiche: Frühstück, Mittag, Abendessen, Snacks. Oben in jedem Bereich steht angepinnt das für diesen Tag und diese Mahlzeit geplante Gericht; ein Tipp übernimmt es.
2. „Gegessen“ fragt die Portionen ab (Vorgabe 1, Schritte 0,25).
3. Darunter drei Wege zum Hinzufügen:
   - **Text:** freie Eingabe wie „200 g Skyr, 1 Banane“, zeilenweise geparst und gegen `foods` gematcht
   - **Rezept:** Suche in der Rezeptliste mit Ranking-Filtern, Portionen wählen
   - **Zutat:** einzelnes Lebensmittel aus BLS, Open Food Facts oder eigenen, Menge in g oder als Einheit
4. Jeder Eintrag wird ein `diary_entry` mit Nährwert-Snapshot; nur diese Einträge zählen für den Tagesbalken.

## Importer

Alle Importer erfüllen dasselbe Interface `parse(eingabe) → RecipeDraft` und liefern nie Nährwerte.

| Quelle | Eingabe | Weg | Stand |
| --- | --- | --- | --- |
| Cookidoo (einzeln) | Teilen-Menü der Cookidoo-App | Kurzbefehl schickt URL + Seitentext per POST an `/api/v1/import/text` | Kurzbefehl existiert, Ziel wird die eigene API statt Health |
| Cookidoo (Sammlung) | ID-Liste aus einem Sammlungs-Link | Pro ID Rezeptseite abrufen, Titel, Portionen, Zutaten, Link extrahieren | Verfahren aus dem Ranking-Widget; Zutaten kommen neu dazu |
| Chefkoch | Rezept-URL | Strukturierte Rezeptdaten der Seite (vermutlich schema.org/Recipe), sonst HTML | Vor Umsetzung prüfen |
| Einfach Backen | Rezept-URL | wie Chefkoch | Vor Umsetzung prüfen |
| Freitext | Eingefügte Zutatenliste | Zeilenweise parsen | Immer verfügbar als Fallback |

Der Cookidoo-Massenimport läuft am Rechner als Skript gegen die API, nicht auf dem Pi. Das hält Login-Fragen und Abruflast vom Pi fern; der Pi nimmt nur fertige Entwürfe an. Bestehende Rezepte werden über die Quell-ID erkannt und nicht doppelt angelegt.

## UI und Übernahme des Ranking-Widgets

Das Widget „Protein-Ranking Fürth“ wird die Rezeptauswahl der App, und sein Look wird das Designsystem für alle Seiten.

**Was übernommen wird**

- Score-Regler Eiweiß/Kalorien, Kategorie-Chips, Suche, Stern für Favoriten, Leiste unten mit Durchschnittswerten
- Score = `w·P̂ + (1−w)·(1−K̂)`, P̂ und K̂ auf Min/Max der gezeigten Kategorie normiert; Standard w = 0,7
- Farb-Tokens: Grün für Eiweiß, Orange für kcal, Hell- und Dunkelmodus, Schriften Bricolage Grotesque, IBM Plex Sans und Mono
- Schmale Spalte, Sticky-Filter oben, mobil zuerst

**Was sich ändert**

- Daten kommen aus `/api/v1/recipes` statt aus eingebettetem JSON
- kcal und Eiweiß pro Portion sind berechnet; Rezepte mit offenen Zutaten tragen ein Kennzeichen (z. B. „9/11“)
- Neue Aktionen je Zeile: „Einplanen“, „Bearbeiten“, „In Cookidoo öffnen“
- Favoriten liegen in der Datenbank statt im Browser

**Seiten**

| Seite | Inhalt |
| --- | --- |
| Heute | Tagesbalken kcal gegen Limit, Makro-Balken, vier Mahlzeiten mit Einträgen und angepinnten Plangerichten |
| Rezepte | Ranking-Ansicht mit Filtern |
| Rezept | Zutatenliste mit Matching-Status, Bearbeiten, Nährwerte pro Portion |
| Plan | 1 oder 2 Wochen, Tag × Mahlzeit, Portionen je Eintrag |
| Lebensmittel | Suche in BLS/OFF/eigenen, eigenes Lebensmittel anlegen, Einheiten pflegen |
| Einstellungen | kcal-Limit, Makro-Ziele, Mahlzeitnamen |

## Tech-Stack, Repo-Struktur, Konfiguration, Deployment

Python mit FastAPI und SQLite, serverseitig gerendert, ohne Frontend-Build; Veröffentlichung über GitHub als Home-Assistant-Add-on-Repository.

| Ebene | Wahl |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic für Migrationen |
| Datenbank | SQLite in `/data/app.db`, Volltextsuche über SQLite FTS5 |
| Frontend | Jinja-Templates, HTMX für Formulare, Vanilla JS für Ranking und Plan |
| Matching | `rapidfuzz` für Ähnlichkeitssuche, eigener Zeilenparser für Menge/Einheit |
| Tests und Qualität | pytest, Ruff |
| Betrieb | HA-Add-on mit Ingress; Port 8099 mit API-Token für Kurzbefehle |

```
tellerplan-ha/
├── CLAUDE.md
├── repository.yaml
├── .github/workflows/   ci.yml · release.yml
├── docs/                Architektur.md · Datenmodell.md
├── tools/               cookidoo_import.py (läuft am Rechner)
└── tellerplan/          ← Add-on
    ├── config.yaml · Dockerfile · run.sh
    └── app/
        ├── main.py · settings.py
        ├── modules/  foods · nutrition · recipes · importers · planner · diary
        ├── api/v1/
        ├── web/      templates/ · static/tokens.css
        ├── migrations/
        ├── scripts/  import_bls.py
        └── tests/
```

**Konfiguration:** Eine Datei `settings.py` liest `options.json` (lokal `./dev/options.json`, im Add-on `/data/options.json`). Darin stehen kcal-Limit, Makro-Ziele, Mahlzeitnamen, API-Token und Datenbankpfad; im Code gibt es keine weiteren Konstanten.

**Deployment:** Push lässt CI laufen. Ein Tag `vX.Y.Z` baut das arm64-Image nach GHCR, Home Assistant zeigt das Update an. Datenbank-Migrationen laufen beim Start des Add-ons automatisch; vorher legt `run.sh` eine Kopie der Datenbank an.

**Lokal:** `uvicorn main:app --reload` auf `localhost:8000`, Test am iPhone über die PC-IP im WLAN.

## Ausbaustufen und offene Punkte

Fünf Stufen, jede einzeln nutzbar; das Kalorienzählen steht nach Stufe 1.

1. **Kern:** Repo, Add-on-Gerüst, CI/Release, BLS-Import, Lebensmittelsuche, Tagebuch mit vier Mahlzeiten, Tageslimit und Balken
2. **Rezepte:** Datenmodell, Freitext-Import, Zeilenparser, Matching mit Alias-Lernen, Nährwerte pro Portion
3. **Cookidoo und Ranking:** Sammlungs-Import am Rechner, Kurzbefehl an die API, Ranking-Widget als Rezeptauswahl
4. **Plan:** 1–2-Wochenplan, Portionen je Eintrag, Übernahme ins Tagebuch mit gegessenen Portionen
5. **Erweiterungen:** Chefkoch, Einfach Backen, Open-Food-Facts-Barcode, Gewicht per Kurzbefehl aus Apple Health

**Offene Punkte**

- [ ] Liefern Chefkoch und Einfach Backen strukturierte Rezeptdaten? Vor Stufe 5 prüfen.
- [ ] Welche Nährstoffe außer kcal, Eiweiß, Fett und KH sollen sichtbar sein (z. B. Ballaststoffe, Zucker)?
- [ ] Wie groß ist die Sammlung „Fürth“, und soll sie komplett oder schrittweise importiert werden?

## Quellen

- BLS 4.0, Lizenz CC BY 4.0, Herausgeber Max Rubner-Institut: https://blsdb.de/download
- Open Food Facts: https://world.openfoodfacts.org
