# Tellerplan – Architektur

Stand: 2026-10-24

## Ziel und Leitentscheidungen

Tellerplan ist eine selbst gehostete App, die Kalorienzählen und Rezeptverwaltung mit Wochenplan vereint: ein GitHub-Repo `tellerplan-ha`, ein Home-Assistant-Add-on mit Slug `tellerplan`, eine SQLite-Datenbank.

| Entscheidung          | Festlegung                                                                                              | Begründung                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Repo-Schnitt          | Ein Repo, eine App, innen nach Modulen getrennt                                                         | Rezepte, Plan und Tagebuch teilen dieselben Lebensmittel und Nährwerte |
| Maßgebliche Nährwerte | Immer aus der eigenen Lebensmitteldatenbank berechnet                                                   | Zutaten werden manuell präzisiert (z. B. welche Sahne)                 |
| Quell-Nährwerte       | Werden beim Import **nicht** übernommen                                                                 | Keine zweite Wahrheit, keine Abweichungen zu pflegen                   |
| Rolle des Imports     | Liefert nur Titel, Portionen, Link und rohe Zutatenliste                                                | Rezepte sind jederzeit editierbar und werden schrittweise gematcht     |
| Portionen             | Rezept hat Standardportionen; der Plan hat eigene Portionen (Vorgabe: Standard); das Tagebuch zählt nur die gegessenen | Planung und Verzehr sind getrennte Fragen                              |
| Historie              | Tagebucheinträge speichern einen Nährwert-Snapshot                                                      | Spätere Rezeptänderungen verändern keine vergangenen Tage              |
| Eintragen             | Nur auf der Seite „Heute“; der Plan kennt keine Mahlzeiten                                              | Ein Ort für das, was wirklich gegessen wurde                           |
| Cookidoo-Planung      | Link zur Rezeptseite wird gespeichert, Planung dort per Link                                            | Keine öffentliche Cookidoo-Schnittstelle zum Einplanen bekannt         |

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
| `planner` | Wochenplan über 1–2 Wochen: Tag → Rezepte mit geplanten Portionen (Vorgabe: Standardportionen des Rezepts) | `recipes` |
| `shopping` | Einkaufsliste aus dem Plan: Zutaten zusammenfassen, Vorratsartikel aussortieren, an Bring senden | `planner`, `recipes` |
| `diary` | Tagebuch mit vier Mahlzeiten, Tageslimit als Halbkreis, Makro-Balken; Übernahme aus dem Plan mit gegessenen Portionen | `nutrition`, `recipes`, `planner` |

Querschnitt: `settings` (zentrale Parameter aus `options.json`), `api` (JSON für UI und Kurzbefehle), `web` (Seiten und UI-Komponenten).

## Datenmodell

Zehn Tabellen; Nährwerte existieren nur an `food`, alles andere verweist darauf oder hält einen Snapshot.

| Tabelle | Wichtige Felder | Regel |
| --- | --- | --- |
| `food` | Name, Quelle (bls / off / custom), Quell-ID, Nährwerte pro 100 g (kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz, weitere als JSON) | Einzige Stelle mit Nährwerten |
| `food_unit` | food_id, Einheit (EL, TL, Stück, Becher, Prise), Gramm | Umrechnung pro Lebensmittel; Dichte für ml |
| `recipe` | Titel, Quelle, `source_url`, Quell-ID, Standardportionen, Kategorie, Tags, Favorit, Notiz, Kochschritte (ein Schritt pro Zeile) | Keine Nährwertfelder |
| `recipe_ingredient` | recipe_id, Reihenfolge, Originaltext, Menge, Einheit, food_id (leer = offen), Gramm, optional-Flag | Jede Zeile frei editierbar, auch nach dem Matching |
| `ingredient_alias` | normalisierter Zutatentext → food_id, Treffer-Anzahl | Wird bei jeder manuellen Zuordnung gelernt |
| `plan_entry` | Datum, recipe_id, Portionen | Ohne Mahlzeit; Portionen beim Einplanen wählbar, Vorgabe sind die Standardportionen des Rezepts (Migration 0007) |
| `diary_entry` | Datum, Mahlzeit, food_id oder recipe_id, Menge + Einheit + Gramm bzw. gegessene Portionen, plan_entry_id, Bezeichnung und Nährwert-Snapshot (kcal, Eiweiß, Fett, KH), Vollständigkeit | Nur diese Einträge zählen für den Tag |
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

1. Im Rezept „Einplanen“ tippen oder im Plan beim Tag auf „+“.
2. Tag und Portionen wählen (Vorgabe: Standardportionen), ohne Mahlzeit. Vom Rezept aus fragt die Seite nur nach Tag und Portionen, aus dem Plan heraus zusätzlich nach dem Rezept. Die Einkaufsliste rechnet die Mengen auf die geplanten Portionen um (geändert am 2026-10-25, vorher galten immer die Standardportionen).
3. Der Plan zeigt drei Tage zurück und zwei Wochen voraus, wahlweise als waagerecht scrollbare Spalten (heute ganz links) oder als Liste (heute direkt unter der festen Kopfzeile); je Tag nur die Rezepttitel.
4. Ein Tipp auf ein Rezept öffnet Aktionen: Rezept öffnen, auf einen anderen Tag verschieben (bei vergangenen Tagen „Auf heute“), entfernen.
5. Cookidoo-Rezepte haben einen Button „In Cookidoo öffnen“, um sie dort einzuplanen.

**Loggen**

1. Eingetragen wird nur auf „Heute“. Ganz oben zeigt ein Halbkreis den Stand gegen das Tageslimit: gefüllt ist das Gegessene, in der Mitte steht der Rest (oder die Überschreitung). Darunter Balken für Eiweiß, Fett und KH gegen die Ziele.
2. Darunter stehen die für den Tag geplanten Rezepte; „Eintragen“ übernimmt eines mit Mahlzeit und gegessenen Portionen (Vorgabe 1, Schritte 0,25) und markiert es als eingetragen.
3. Dann die vier Bereiche Frühstück, Mittag, Abendessen, Snacks, je mit „+“ zum Hinzufügen:
   - **Rezept:** Auswahl aus der Rezeptliste, Portionen wählen
   - **Lebensmittel:** einzelnes Lebensmittel, Menge in g oder als Einheit
   - **Text** (Stufe 4): freie Eingabe wie „200 g Skyr, 1 Banane“, zeilenweise geparst und gegen `foods` gematcht
4. Jeder Eintrag wird ein `diary_entry` mit Nährwert-Snapshot; nur diese Einträge zählen für den Tagesbalken.

## Lebensmitteldaten aus BLS 4.0

Der Bundeslebensmittelschlüssel liefert rund 7.140 Lebensmittel mit Werten pro 100 g; er wird einmal am Rechner umgewandelt und dann per Migration eingespielt.

| Schritt | Wo | Was |
| --- | --- | --- |
| Umwandeln | Rechner, `tools/bls_convert.py` | Excel-Datei des MRI → `tellerplan/app/data/bls_4_0.csv` mit BLS-Code, Name und sieben Nährwerten (kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz); „TR“/„<LOD“ → 0, „-“ → leer |
| Einspielen | Add-on-Start, Migration `0005` | Lebensmittel mit `source = bls` und BLS-Code als `source_id`; vorhandene Einträge werden über den Code aktualisiert, Rezeptverweise bleiben erhalten |
| Anzeigen | Lebensmittel-Seiten | Kennzeichen „BLS“ bzw. „eigen“, Quellenangabe (CC BY 4.0); BLS-Werte schreibgeschützt, Einheiten (z. B. 1 Stück) ergänzbar |

Eine neue BLS-Version heißt: CSV neu erzeugen und eine weitere Datenmigration nach dem Muster von `0005` anlegen. BLS kennt keine Portionsgrößen; Einheiten pflegt der Nutzer pro Lebensmittel.

**Suche:** Bei 7.000 Einträgen reicht SQL mit einem normalisierten Suchschlüssel (Kleinschreibung, Wörter zusammengeschrieben, also „haferflocken“ = „Hafer Flocken“) plus Ranking in Python: ganzes Wort vor Wortanfang vor Wortende, Treffer im ersten Wort (BLS-Namen beginnen mit dem Lebensmittel), dann „roh“, eigene Einträge und kurze Namen. Ohne Treffer folgt eine unscharfe Suche mit `rapidfuzz` („brokkoli“ → „Broccoli roh“). FTS5 ist damit vorerst nicht nötig; mehrdeutige Kurzwörter wie „ei“ löst später das Alias-Lernen.

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

Die Tab-Leiste hat drei Einträge: **Heute · Plan · Rezepte**. Einstellungen erreicht man über das Zahnrad oben rechts auf „Heute“, die Lebensmittel über die Einstellungen sowie beim Eintragen und beim Zuordnen von Zutaten. Festgelegt am 2026-10-25: Heute und Plan braucht man täglich, Rezepte beim Planen, Lebensmittel und Einstellungen nur gelegentlich.

| Seite | Inhalt |
| --- | --- |
| Heute | Tages-Dashboard: Halbkreis kcal gegen Limit, Makro-Balken, geplante Rezepte zum Übernehmen, vier Mahlzeiten mit Einträgen; einziger Ort zum Eintragen |
| Rezepte | Ranking-Ansicht mit Filtern |
| Rezept | Zutatenliste mit Matching-Status, Nährwerte pro Portion; Buttons Einplanen, Kochen, Bearbeiten und rechts „In Cookidoo öffnen“ |
| Kochen | Unterseite eines Rezepts: nummerierte Kochschritte, links schmal die mitlaufende Zutatenliste; die Schritte erscheinen nur hier |
| Plan | 3 Tage zurück bis 2 Wochen voraus, Spalten oder Liste (Umschalter oben rechts), nur Rezepttitel, Verschieben auf andere Tage; Knopf „🛒 Einkaufsliste“ |
| Einkaufsliste | Unterseite des Plans: gesendete Artikel mit Mengen und Rezepten, übersprungener Vorrat, Liste als Text zum Kopieren |
| Einstellungen | Zahnrad auf „Heute“: Tageslimit kcal und Makro-Ziele, Bring-Liste und Vorrat, Link zu den Lebensmitteln; Mahlzeitnamen und API-Token nur in Home Assistant |
| Lebensmittel | Unterseite der Einstellungen: Suche in BLS/OFF/eigenen, eigenes Lebensmittel anlegen, Einheiten und Einkaufsname pflegen |

## Tech-Stack, Repo-Struktur, Konfiguration, Deployment

Python mit FastAPI und SQLite, serverseitig gerendert, ohne Frontend-Build; Veröffentlichung über GitHub als Home-Assistant-Add-on-Repository.

| Ebene | Wahl |
| --- | --- |
| Backend | Python 3.14, FastAPI, SQLAlchemy 2, Alembic für Migrationen |
| Datenbank | SQLite in `/data/app.db`; Lebensmittelsuche über normalisierten Suchschlüssel, FTS5 erst bei Bedarf |
| Frontend | Jinja-Templates, HTMX für Formulare, Vanilla JS für Ranking und Plan |
| Matching | `rapidfuzz` für Ranking und unscharfe Suche, eigener Zeilenparser für Menge/Einheit |
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
        ├── modules/  foods · nutrition · recipes · importers · planner · shopping · diary
        ├── api/v1/
        ├── web/      templates/ · static/tokens.css
        ├── migrations/
        ├── scripts/  import_bls.py
        └── tests/
```

**Konfiguration:** Eine Datei `settings.py` liest `options.json` (lokal `./dev/options.json`, im Add-on `/data/options.json`). Darin stehen kcal-Limit, Makro-Ziele, Mahlzeitnamen, API-Token und Datenbankpfad; im Code gibt es keine weiteren Konstanten.

**Deployment:** Push lässt CI laufen. Ein Tag `vX.Y.Z` baut das arm64-Image nach GHCR, Home Assistant zeigt das Update an. Datenbank-Migrationen laufen beim Start des Add-ons automatisch; vorher legt `run.sh` eine Kopie der Datenbank an.

**Lokal:** `uvicorn main:create_app --factory --reload` auf `localhost:8000`, Test am iPhone über die PC-IP im WLAN.

**Rechte des Add-ons:** Jedes Add-on läuft in einem abgeschotteten Container und darf von sich aus nicht mit Home Assistant sprechen. Zwei Schalter in `tellerplan/config.yaml` öffnen gezielt je einen Zugang. Gemeint ist die `config.yaml` des Add-ons, nicht die `configuration.yaml` von Home Assistant.

| Option | Öffnet den Zugang zu … | Wofür Tellerplan das braucht |
| --- | --- | --- |
| `hassio_api: true` | Supervisor-API (`http://supervisor/…`): Verwaltung von Apps, Backups und System | Die Einstellseite speichert über `POST /addons/self/options`, genau wie „Speichern“ im Reiter „Konfiguration“ |
| `homeassistant_api: true` | Home-Assistant-API (`http://supervisor/core/api/…`): Entitäten und Aktionen | Die Einkaufsliste ruft `todo.add_item` für die Bring-Liste auf |

Ist ein Schalter gesetzt, gibt der Supervisor dem Container beim Start einen Schlüssel als Umgebungsvariable `SUPERVISOR_TOKEN` mit. Tellerplan schickt ihn bei jeder Anfrage mit, und der Supervisor prüft, ob der Zugang laut `config.yaml` erlaubt ist. Ein Passwort oder ein selbst angelegter Token ist nicht nötig.

Wie viel das Add-on in der Supervisor-API darf, legt `hassio_role` fest. Ohne Angabe gilt `default`: Informationen lesen und die **eigenen** Optionen ändern, aber keine anderen Apps steuern und keine Backups anlegen. Das reicht für Tellerplan. `homeassistant_api` erlaubt dagegen grundsätzlich jede Aktion in Home Assistant; Tellerplan nutzt nur `todo.add_item`. Jeder der beiden Schalter senkt die Sicherheitsbewertung, die Home Assistant beim Add-on anzeigt. Das ist so vorgesehen.

## Ausbaustufen und offene Punkte

Fünf Stufen, jede einzeln nutzbar. Die Reihenfolge wurde am 2026-10-24 umgestellt: erst die Funktionen mit eigenen Daten (Lebensmittel, Rezepte, Plan, Tagebuch), danach die Importe.

1. **Kern:** Repo, Add-on-Gerüst, CI/Release, UI-Rahmen mit Tab-Leiste, Lebensmittel manuell und als Demo-Set, Nährwertrechnung
2. **Rezepte und Plan:** Rezept-Datenmodell, Rezeptliste im Ranking-Look, Rezept anlegen mit Zutaten aus den Lebensmitteln, Nährwerte pro Portion, 1–2-Wochenplan als Tagesliste
3. **Tagebuch:** vier Mahlzeiten, Tageslimit als Halbkreis und Makro-Balken, Übernahme aus dem Plan mit gegessenen Portionen
4. **Importe:** BLS-Import (erledigt), Freitext-Import, Zeilenparser, Matching mit Alias-Lernen, Cookidoo-Sammlung am Rechner, Kurzbefehl an die API
5. **Erweiterungen:** Chefkoch, Einfach Backen, Open-Food-Facts-Barcode, Gewicht per Kurzbefehl aus Apple Health

**Vor Stufe 4** (festgelegt am 2026-10-25)

- **Einkaufsliste** (erledigt, im Add-on noch zu testen): Der Knopf „🛒 Einkaufsliste“ im Plan sendet alle Zutaten der Planeinträge von heute bis heute + 13 Tage direkt an Bring und zeigt danach die Seite „Einkaufsliste“ mit dem Ergebnis. Modul `shopping`, nutzt `planner` und `recipes`, rechnet keine Nährwerte.
  - **Zusammenfassen:** Gleiche Artikel (gleicher Einkaufsname) werden je Einheit addiert, nicht in Gramm, weil „5 Stück“ beim Einkaufen mehr hilft als „290 g“: „2 Stück + 3 Stück“ → „5 Stück“, gemischt „1 Dose + 200 g“. Offene Zutaten erscheinen mit ihrem Originaltext; Artikel, die in allen Rezepten optional sind, tragen „optional“.
  - **Vorrat:** Stichwörter in `pantry_keywords` (Regel 6, einstellbar in HA und auf der Einstellseite). Ein Stichwort trifft jedes Wort, das damit endet; deutsche Zusammensetzungen tragen das Grundwort hinten, also trifft „salz“ „Meersalz“, „zucker“ aber nicht „Zuckerschote“. Übersprungene Artikel zeigt die Seite einklappbar an.
  - **Name:** `food.shopping_name`, sonst aus dem BLS-Namen abgeleitet: Teil vor „, “ und „/“, ohne Gehaltsangaben („mind. 30 % Fett“) und ohne „roh“/„reif“ am Ende. „Karotte/Möhre, roh“ → „Karotte“.
  - **Senden:** Je Artikel `todo.add_item` über die Supervisor-API mit dem Namen als `item` und der Menge als `description` (in Bring die Spezifikation). Bring führt gleichnamige Artikel zusammen, erneutes Senden aktualisiert also nur die Menge. Ziel-Liste ist `bring_list_entity` (z. B. `todo.furth`), Recht `homeassistant_api: true`. Tellerplan kennt kein Bring-Passwort. Lokal ohne Supervisor sendet der Knopf nichts; die Seite bietet die Liste zum Kopieren an.
- **Einstellseite** (erledigt, im Add-on noch zu testen): Tageslimit kcal, Eiweißziel sowie Fett- und KH-Ziel lassen sich in der App ändern, bisher geht das nur in Home Assistant unter Add-on → Konfiguration. Beim Speichern schreibt das Add-on seine eigenen Optionen über die Supervisor-API (`POST /addons/self/options`, dafür `hassio_api: true` in `config.yaml`) und lädt danach `settings` neu, ein Neustart ist nicht nötig. Lokal schreibt die Seite direkt in `dev/options.json`. `options.json` bleibt damit die einzige Quelle (Regel 6). Vergangene Tage zeigen danach das neue Ziel, denn Ziele werden nicht pro Tag gespeichert.
- **CI und Release prüfen:** CI läuft bei jedem Push erfolgreich. Der Release-Workflow lief noch nie, es gibt noch keinen Tag; der erste Tag `v0.1.0` muss also das arm64-Image bauen und nach GHCR legen.
- **Live-Betrieb auf dem Raspberry Pi:** Repository in Home Assistant hinzufügen, Add-on installieren, `api_token` setzen und Ingress auf dem iPhone testen. Port 8099 erst freigeben, wenn HTTPS geklärt ist (siehe unten).

**Offene Punkte**

- [x] Wie kommt die Einkaufsliste zu Bring? Über die Bring-Integration von Home Assistant mit `todo.add_item`, am 2026-10-25 von Hand getestet: Artikel und Spezifikation kommen in Bring an. Das Teilen-Menü ist damit nicht nötig.
- [ ] Kontrollseite vor dem Senden an Bring? Eine Seite mit allen Zutaten zum Abhaken: Vorratsartikel sind nicht angehakt, alle anderen schon; Mengen lassen sich anpassen, erst „Bestätigen“ schickt die Liste an Bring. Vorerst nicht umsetzen, sondern im Alltag prüfen, ob die direkte Übergabe reicht.
- [ ] Braucht die Einstellseite `hassio_api` wirklich? Laut Supervisor-Quellcode sind Aufrufe an `/addons/self/…` womöglich auch ohne erreichbar. Beim ersten Test im Add-on prüfen und den Schalter entfernen, falls er unnötig ist.
- [x] Vorratsliste: Stichwörter als Option `pantry_keywords` in `options.json` (z. B. „salz“ trifft alle Salz-Einträge aus BLS), einstellbar in HA und auf der Einstellseite. Kein Kennzeichen am Lebensmittel.
- [x] Artikelnamen: neues optionales Feld „Einkaufsname“ an `food` (z. B. „Hähnchenbrust“), gepflegt in der Lebensmittel-Ansicht, Migration 0006. Ohne Eintrag wird der Name aus dem BLS-Namen abgeleitet.

- [ ] Liefern Chefkoch und Einfach Backen strukturierte Rezeptdaten? Vor Stufe 5 prüfen.
- [x] Welche Nährstoffe werden übernommen? Aus BLS die sieben vorhandenen Felder (kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz); weitere lassen sich aus der Excel-Datei nachziehen. Offen bleibt, welche davon die Oberfläche zeigt.
- [ ] HTTPS für die API auf Port 8099, vor dem Cookidoo-Kurzbefehl in Stufe 4: Bisher spricht der Port direkt HTTP, ein Token von unterwegs ginge unverschlüsselt. Optionen: Zertifikate von Home Assistant einbinden (`map: ssl` in `config.yaml`, uvicorn mit `/ssl/fullchain.pem` und `/ssl/privkey.pem`) oder Zugriff über einen vorhandenen Reverse Proxy. Ingress ist nicht betroffen, dort übernimmt Home Assistant HTTPS. Lokal bleibt HTTP; Browser-Funktionen wie Kamera (Barcode, Stufe 5) oder Bildschirm wach halten brauchen auf dem iPhone eine HTTPS-Verbindung, also Ingress.
- [ ] Sollen Importer auch Kochschritte übernehmen (bisher nur von Hand)? Regel 2 erlaubt aktuell nur Titel, Portionen, Link, Quell-ID und Zutatenzeilen.
- [ ] Wie groß ist die Sammlung „Fürth“, und soll sie komplett oder schrittweise importiert werden?

## Quellen

- BLS 4.0, Lizenz CC BY 4.0, Herausgeber Max Rubner-Institut: https://blsdb.de/download
- Open Food Facts: https://world.openfoodfacts.org
