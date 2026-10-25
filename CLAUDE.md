# CLAUDE.md – Tellerplan

Tellerplan ist eine selbst gehostete Kalorien- und Rezept-App für einen Nutzer.
Sie läuft als Home-Assistant-Add-on auf einem Raspberry Pi.
Die vollständige Architektur steht in `docs/Architektur.md`. Lies sie vor jeder größeren Änderung.

## Sprache

- Dokumentation, Commit-Messages, UI-Texte und Kommentare: **Deutsch**
- Bezeichner im Code (Module, Klassen, Funktionen, Tabellen, Spalten): **Englisch**

## Unverrückbare Regeln

1. **Nährwerte existieren nur an `food`** (pro 100 g). Rezepte, Plan und Tagebuch speichern keine eigenen Nährwertfelder.
2. **Importer liefern nie Nährwerte.** Ein Import erzeugt nur Titel, Standardportionen, Quell-Link, Quell-ID und rohe Zutatenzeilen. Nährwertangaben der Quelle (Cookidoo, Chefkoch …) werden verworfen.
3. **Nur `modules/nutrition` rechnet Nährwerte.** Alle anderen Module fragen es.
4. **`diary_entry` speichert einen Nährwert-Snapshot.** Spätere Rezeptänderungen dürfen vergangene Tage nicht verändern.
5. **Portionen:** Rezept = Standardportionen; `plan_entry` = Rezept an einem Tag, immer mit seinen Standardportionen (keine Mahlzeit, keine eigenen Portionen); `diary_entry` = gegessene Portionen. Nur das Tagebuch zählt für die Tageswerte, eingetragen wird nur auf „Heute“.
6. **Zentrale Parameter:** Alle konfigurierbaren Werte (kcal-Limit, Makro-Ziele, Mahlzeitnamen, API-Token, DB-Pfad) kommen ausschließlich über `app/settings.py` aus `options.json`. Keine verstreuten Konstanten oder Magic Numbers im Code.
7. **Ein Repo, eine App, eine Datenbank.** Modulgrenzen einhalten, keine Querimporte an der Abhängigkeitsrichtung vorbei:
   `foods` ← `nutrition` ← `recipes` ← `importers`, `recipes` ← `planner`, (`recipes`, `planner`) ← `shopping`, (`nutrition`, `recipes`, `planner`) ← `diary`

## Stil

- Sauberer, wartbarer Code vor Cleverness; kleine Funktionen, Typannotationen überall
- Lieber ein einfacher, lesbarer Weg als ein generisches Framework
- Iterativ arbeiten: kleine, lauffähige Schritte, jeder mit Tests
- Jede Schemaänderung als Alembic-Migration, nie manuell an der DB

## Stack

- Python 3.14, FastAPI, SQLAlchemy 2, Alembic, SQLite, rapidfuzz
- Jinja-Templates + HTMX, Vanilla JS für Ranking und Wochenplan, **kein Frontend-Build**
- Design-Tokens in `web/static/tokens.css` (aus dem Widget „Protein-Ranking Fürth“: Grün = Eiweiß, Orange = kcal, Hell/Dunkel, Bricolage Grotesque / IBM Plex)
- pytest, Ruff

## Struktur

```
tellerplan-ha/
├── repository.yaml            HA-Add-on-Repository
├── .github/workflows/         ci.yml (ruff + pytest), release.yml (arm64-Image → GHCR)
├── .obsidian/                 Obsidian-Einstellungen (Vault = Repo, sichtbar nur docs/)
├── docs/                      Projektdoku als Obsidian-Vault (Start.md, Architektur.md, Entwicklung.md)
├── dev/                       lokale options.json + DB (nicht im Git, Vorlage options.example.json)
├── tools/                     Skripte für den Rechner: bls_convert.py (später cookidoo_import.py)
└── tellerplan/                das Add-on
    ├── config.yaml            version = einzige Versionsquelle
    ├── Dockerfile · run.sh · DOCS.md
    └── app/
        ├── main.py · settings.py · db.py · migrate.py
        ├── security.py        Zugriff je Port (Ingress ohne Login, 8099 mit Token)
        ├── supervisor.py      Aufrufe an die Supervisor-API (nur im Add-on)
        ├── serve.py           Add-on-Start: Backup, Migration, beide Ports
        ├── modules/           foods · nutrition · recipes · importers · planner · shopping · diary
        ├── api/v1/            JSON-API (UI, Kurzbefehle, Skripte)
        ├── web/               templates/ · static/
        ├── data/              bls_4_0.csv (aus BLS 4.0, CC BY 4.0, Quelle nennen)
        ├── migrations/        0005 spielt BLS ein, 0006 Einkaufsname
        ├── scripts/           seed_demo.py · import_bls.py (später)
        └── tests/
```

## Befehle

```bash
# Einrichten
cd tellerplan/app
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Starten (lokal, Auto-Reload)
TELLERPLAN_OPTIONS=../../dev/options.json uvicorn main:create_app --factory --reload --host 0.0.0.0 --port 8000

# Starten wie im Add-on (Backup, Migration, Ports 8000 und 8099)
TELLERPLAN_OPTIONS=../../dev/options.json python -m serve

# Demo-Set laden (Lebensmittel + Rezepte, mehrfach ausführbar)
TELLERPLAN_OPTIONS=../../dev/options.json python -m scripts.seed_demo

# Prüfen
ruff check . && ruff format --check .
pytest

# Migration anlegen
alembic revision --autogenerate -m "<beschreibung>"

# BLS-CSV neu erzeugen (im Repo-Root, Excel liegt in dev/bls/)
pip install -r tools/requirements.txt
python tools/bls_convert.py dev/bls/BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx tellerplan/app/data/bls_4_0.csv
```

Tests nutzen eine migrierte Datenbank **ohne** BLS-Daten (`upgrade_to_head(..., skip_data_migrations=True)`); nur `test_database.py` prüft den echten Import.

Lokale Konfiguration und Datenbank liegen in `dev/` (in `.gitignore`); Vorlage ist `dev/options.example.json`.

## Dokumentation

- Projektdoku liegt in `docs/` und wird mit Obsidian gepflegt; Einstieg ist `docs/Start.md`.
- Neue Doku-Notizen immer unter `docs/` anlegen, Wikilinks `[[Notiz]]` sind erlaubt.

## Release

1. `version` in `tellerplan/config.yaml` erhöhen
2. Tag `vX.Y.Z` pushen (muss zur Version passen, der Workflow prüft das)
3. GitHub Action baut `ghcr.io/<owner>/tellerplan-aarch64:X.Y.Z`, Home Assistant zeigt das Update

## Sicherheit

- Niemals Tokens, `options.json`, Datenbanken oder Exporte committen
- API auf Port 8099 nur mit Token (`Authorization: Bearer …`); Ingress-Seiten ohne eigenes Login

## Ausbaustufen

1. **Kern:** Gerüst, CI/Release, UI-Rahmen (Tab-Leiste), Lebensmittel manuell + Demo-Set, Nährwertrechnung
2. **Rezepte und Plan:** Rezept-Datenmodell, Rezeptliste im Ranking-Look, Rezept anlegen mit Zutaten aus den Lebensmitteln, Nährwerte pro Portion, 1–2-Wochenplan als Tagesliste
3. **Tagebuch:** vier Mahlzeiten, Tageslimit als Halbkreis, Makro-Balken, Übernahme aus dem Plan mit gegessenen Portionen
4. **Importe:** BLS-Import (erledigt), Freitext-Import, Zeilenparser, Matching mit Alias-Lernen, Cookidoo-Sammlung am Rechner, Kurzbefehl an die API
5. **Erweiterungen:** Chefkoch, Einfach Backen, Open-Food-Facts-Barcode, Gewicht per Kurzbefehl

Aktuelle Stufe: **3**
