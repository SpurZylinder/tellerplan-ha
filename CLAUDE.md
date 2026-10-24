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
5. **Portionen:** Rezept = Standardportionen; `plan_entry` = geplante Portionen (änderbar); `diary_entry` = gegessene Portionen. Nur das Tagebuch zählt für die Tageswerte.
6. **Zentrale Parameter:** Alle konfigurierbaren Werte (kcal-Limit, Makro-Ziele, Mahlzeitnamen, API-Token, DB-Pfad) kommen ausschließlich über `app/settings.py` aus `options.json`. Keine verstreuten Konstanten oder Magic Numbers im Code.
7. **Ein Repo, eine App, eine Datenbank.** Modulgrenzen einhalten, keine Querimporte an der Abhängigkeitsrichtung vorbei:
   `foods` ← `nutrition` ← `recipes` ← `importers`, `recipes` ← `planner`, (`nutrition`, `planner`) ← `diary`

## Stil

- Sauberer, wartbarer Code vor Cleverness; kleine Funktionen, Typannotationen überall
- Lieber ein einfacher, lesbarer Weg als ein generisches Framework
- Iterativ arbeiten: kleine, lauffähige Schritte, jeder mit Tests
- Jede Schemaänderung als Alembic-Migration, nie manuell an der DB

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite (FTS5), rapidfuzz
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
├── tools/                     Skripte für den Rechner (z. B. cookidoo_import.py)
└── tellerplan/                das Add-on
    ├── config.yaml            version = einzige Versionsquelle
    ├── Dockerfile · run.sh · DOCS.md
    └── app/
        ├── main.py · settings.py · db.py · migrate.py
        ├── security.py        Zugriff je Port (Ingress ohne Login, 8099 mit Token)
        ├── serve.py           Add-on-Start: Backup, Migration, beide Ports
        ├── modules/           foods · nutrition · recipes · importers · planner · diary
        ├── api/v1/            JSON-API (UI, Kurzbefehle, Skripte)
        ├── web/               templates/ · static/
        ├── migrations/
        ├── scripts/           import_bls.py
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

# Prüfen
ruff check . && ruff format --check .
pytest

# Migration anlegen
alembic revision --autogenerate -m "<beschreibung>"
```

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

1. **Kern:** Gerüst, CI/Release, BLS-Import, Lebensmittelsuche, Tagebuch (Frühstück, Mittag, Abendessen, Snacks), Tageslimit, Balken
2. **Rezepte:** Datenmodell, Freitext-Import, Zeilenparser, Matching mit Alias-Lernen, Nährwerte pro Portion
3. **Cookidoo und Ranking:** Sammlungs-Import am Rechner, Kurzbefehl an die API, Ranking-Widget als Rezeptauswahl
4. **Plan:** 1–2-Wochenplan, Portionen je Eintrag, Übernahme ins Tagebuch
5. **Erweiterungen:** Chefkoch, Einfach Backen, Open-Food-Facts-Barcode, Gewicht per Kurzbefehl

Aktuelle Stufe: **1**
