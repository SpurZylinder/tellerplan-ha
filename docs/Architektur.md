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
│ iPhone: Web-App  │  │ iPhone: Kurzbefehle  │  │ Rechner: Skripte          │
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

Die Oberfläche läuft auf zwei Wegen: über Ingress im Rahmen von Home Assistant (ohne eigenes Login) oder als Vollbild-App direkt auf Port 8099 mit Anmeldung über Home Assistant (siehe „Vollbild-App“). Kurzbefehle und Rechner-Skripte sprechen die API auf Port 8099 unter `/api/…` mit Token an. Externe Daten (BLS, Open Food Facts, Rezeptseiten) kommen nur über `foods` und `importers` herein.

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

Nährwerte existieren nur an `food`, alles andere verweist darauf oder hält einen Snapshot; einzige Ausnahme sind die Vergleichswerte in `recipe_reference`, die nie gerechnet werden.

| Tabelle | Wichtige Felder | Regel |
| --- | --- | --- |
| `food` | Name, Quelle (bls / off / rewe / custom), Quell-ID (BLS-Code, Barcode, bei eigenen eine erzeugte Kennung), Barcode (eindeutig), Hersteller, Packungsgröße, Kurzname, Nährwerte pro 100 g | Einzige Stelle mit Nährwerten; ein Produkt mit Barcode gibt es nur einmal, egal aus welcher Quelle |
| `food_unit` | food_id, Einheit (EL, TL, Stück, Becher, Prise), Gramm | Umrechnung pro Lebensmittel; Dichte für ml |
| `recipe` | Titel, Quelle, `source_url`, Quell-ID, Standardportionen, Kategorie, Tags, Favorit, Notiz, Kochschritte (ein Schritt pro Zeile) | Keine Nährwertfelder |
| `recipe_ingredient` | recipe_id, Reihenfolge, Originaltext, Name („Milch“), Menge, Einheit, Grundzutat, food_id nur bei im Rezept bewusst gewähltem Produkt, optional-Flag | Gerechnet wird das gewählte Produkt, sonst das Standardprodukt der Grundzutat. Ohne Menge („Salz“): „nach Bedarf“, zählt nicht gegen die Vollständigkeit |
| `base_ingredient` | Name („Milch“, „Vollmilch“, „Kreuzkümmel“), Standardprodukt, Kennzeichen „ohne Nährwerte“; Produkte über `base_ingredient_food` (ein Produkt kann zu mehreren gehören) | Spezialisierungen sind eigene Grundzutaten, auch mit gleichem Standardprodukt |
| `ingredient_alias` | Schlüssel des Zutatennamens (klein, z. B. „frische milch“) → Grundzutat | Beim Zuordnen gelernt, bei jedem Import sofort angewendet |
| `recipe_reference` | recipe_id, kcal, Eiweiß, Fett, KH pro Portion laut Quelle | Nur Vergleichswert zum Erkennen falscher Zuordnungen, nie gerechnet (Regel 1 und 2) |
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

Festgelegt am 2026-10-25 (Grundzutaten). Drei Ebenen, damit das Rezept von „Milch“ spricht und die Rechnung ein bestimmtes Produkt nimmt:

```
Rezeptzeile   "200 ml Milch"   Name, Menge, Einheit · optional bewusst gewähltes Produkt
   ▼
Grundzutat    Milch            Standardprodukt · „ohne Nährwerte“ ja/nein · Namen, die darauf zeigen
   ▼
Produkte      Laktosefreie H-Milch 1,5 % (Berchtesgadener Land) ← Standard, weitere zur Auswahl
```

1. **Zuordnen** (Rezepte → „Zuordnen“): Jeder Zutatenname ohne Grundzutat erscheint einmal, häufigste zuerst. Man wählt eine bestehende Grundzutat oder legt eine neue an, optional gleich mit Standardprodukt, oder markiert sie als „ohne Nährwerte“ (Gewürze: zählen als vollständig mit 0 kcal, weder Produkt noch Grammzahl nötig). Der Name wird gelernt und gilt für alle Rezepte und künftigen Importe.
2. **Spezialisierungen** wie „Vollmilch“ oder „Kokosmilch“ sind eigene Grundzutaten, auch wenn sie dasselbe Standardprodukt haben wie „Milch“; so lassen sie sich später getrennt umstellen.
3. **Standard ändern** (Seite „Grundzutaten“) wirkt sofort in allen Rezepten, ohne Zeilen umzuschreiben, weil Zeilen nur auf die Grundzutat zeigen.
4. **Ausnahme im Rezept:** Ein Klick auf eine Zeile zeigt Standard und Produkte ihrer Grundzutat; ein dort gewähltes Produkt gilt nur in diesem Rezept und bleibt, wenn sich der Standard ändert.
5. **Ohne Produkt:** Grundzutaten, die in Rezepten vorkommen, aber noch kein Standardprodukt haben, sammelt ein eigener Bereich.
6. **Einheiten:** fehlende Grammzahlen je gerechnetem Produkt und Einheit; ein Eintrag gilt überall.
7. **Anzeige:** Rezept und Kochansicht zeigen nur „200 ml Milch“ (ohne ergänztes „Stück“, Einheiten im Plural: „2 Prisen“). Die Aufschlüsselung „Nährwerte je Zutat“ zeigt das gerechnete Produkt mit Hersteller und kcal, dazu die Vergleichswerte der Quelle.
8. **Hersteller:** Markenprodukte zeigen in Listen den Hersteller statt „eigen“/„BLS“; die BLS-Quellenangabe bleibt auf Detailseite und in der Lebensmittel-Liste.

**Suche nach deutscher Wortbildung:** Zuerst zählt das Hauptwort (erstes Wort): gleich vor „endet mit“ vor „beginnt mit“, denn „Speisesalz“ ist ein Salz, „Salzkartoffeln“ sind Kartoffeln. Erst danach zählt, wie oft der Begriff sonst im Namen steht. Vorher lieferte „Salz“ zuerst „Salzkartoffeln (Kartoffeln mit Salz gekocht)“.

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

## Produkte aus REWE und Open Food Facts

Festgelegt am 2026-10-26. Markenprodukte (z. B. die Milch als Standard der Grundzutat „Milch“) kommen am Rechner zusammen und werden als Datei im Format `tellerplan-foods` importiert (Einstellungen → „Importieren“).

1. **Favoriten aus dem Browser:** `tools/rewe_har_extract.py` liest einen Firefox-HAR-Mitschnitt und übernimmt nur feste Felder: Favoriten (Produkt-ID, Name, Packung, Link), Bestellpositionen (Titel, EAN, Menge, Kategorie) und im Browser geöffnete Produktseiten. Preise, Kennungen, Telefonnummer, Kommentare und Adressen werden verworfen; ein Selbsttest bricht ab, falls doch etwas davon in einer Ausgabe landet. Die HAR-Datei selbst enthält Cookies und Bestelldaten und wird nach dem Extrahieren gelöscht.
2. **Nährwerte:** `tools/rewe_fetch.py` fragt selbst nichts bei REWE an – automatisierte Abrufe lehnt REWE ab (403), und diese Sperre wird nicht umgangen. Quellen: im Browser geöffnete Produktseiten (JSON-LD mit Barcode und Hersteller, Nährwerttabelle nach GS1) und Open Food Facts über den Barcode (gedrosselt, bei 429 Pause). Was fehlt, steht in einer Linkliste (`…_offen.html`), die man im Browser bei laufendem Mitschnitt abarbeitet.
3. **Import:** Wiedererkennung am Barcode, sonst an Quelle und Quell-ID; ein erneuter Import aktualisiert Nährwerte, Hersteller und Packung, von Hand gepflegte Einheiten und Kurznamen bleiben. Angaben je 100 ml werden wie je 100 g gespeichert, dazu die Einheiten „ml“ (1 ml = 1 g) und „l“; aus der Packungsgröße entsteht die Einheit „Packung“.
4. **Suche:** Bei Markenprodukten zählt das erste Wort nach Hersteller und „Bio“ als Hauptwort („Berchtesgadener Land Bio Milch“ → „Milch“).

Stand der ersten Runde: 185 Favoriten, 24 Produkte mit Nährwerten (23 über Open Food Facts), der Rest in der Linkliste.

## Importer

Alle Importer erfüllen dasselbe Interface `parse(eingabe) → RecipeDraft` und liefern nie Nährwerte.

| Quelle | Eingabe | Weg | Stand |
| --- | --- | --- | --- |
| Cookidoo (einzeln) | Teilen-Menü der Cookidoo-App | Kurzbefehl schickt URL + Seitentext per POST an `/api/v1/import/text` | Kurzbefehl existiert, Ziel wird die eigene API statt Health |
| Cookidoo (Sammlung) | Sammlung als JSON aus dem Ranking-Widget (ID, Titel, Portionen, Link …) | `tools/cookidoo_fetch.py` lädt je ID die öffentliche Rezeptseite gedrosselt, nimmt aus den strukturierten Daten (JSON-LD, schema.org/Recipe) nur `recipeIngredient` und schreibt Entwürfe im Format `tellerplan-recipes` | Umgesetzt 2026-10-25: 172 Rezepte, 2.529 Zeilen |
| Chefkoch | Rezept-URL | Strukturierte Rezeptdaten der Seite (vermutlich schema.org/Recipe), sonst HTML | Vor Umsetzung prüfen |
| Einfach Backen | Rezept-URL | wie Chefkoch | Vor Umsetzung prüfen |
| Freitext | Eingefügte Zutatenliste | Zeilenweise parsen | Immer verfügbar als Fallback |

Der Cookidoo-Abruf läuft am Rechner, nicht auf dem Pi. Das hält Login-Fragen und Abruflast vom Pi fern; der Pi nimmt nur fertige Entwürfe an, hochgeladen unter Einstellungen → „Rezepte importieren“. Bestehende Rezepte werden über Quelle und Quell-ID erkannt (eindeutiger Index) und nicht doppelt angelegt; ein erneuter Import aktualisiert Titel, Portionen, Kategorie, Link, Notiz und Vergleichswerte, lässt aber Zutaten und Zuordnungen unverändert.

**Zeilenparser** (`modules/importers/line_parser.py`): Menge mit Brüchen und Bereichen (Mittelwert), Zusätze wie „geh.“ als Notiz, Einheiten in einheitlicher Schreibweise („Prisen“ → „Prise“, „Pck.“ → „Packung“), Notizen aus Klammern und nach „, “. Eine Menge ohne Einheit bekommt „Stück“, nie Gramm (K9).

**Migrationen und SQLite:** Während der Migrationen sind Fremdschlüssel ausgeschaltet. SQLite baut Tabellen für manche Änderungen neu auf; mit aktiven Fremdschlüsseln hätte ON DELETE CASCADE dabei abhängige Zeilen gelöscht (beim Bau von 0010 durch einen Test aufgefallen).

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
| Lebensmittel | Unterseite der Einstellungen: Suche in BLS/OFF/eigenen, eigenes Lebensmittel mit Hersteller anlegen, Einheiten und Kurzname pflegen |
| Zuordnen | Von Rezepte aus: offene Zutatennamen → Grundzutat, Grundzutaten ohne Produkt, fehlende Einheiten |
| Grundzutaten | Standardprodukt, weitere Produkte, Namen, „ohne Nährwerte“ |
| Zeile im Rezept | Name, Menge, Einheit, Grundzutat und Produkt nur für dieses Rezept |

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

**Deployment:** Push lässt CI laufen. Ein Tag `vX.Y.Z` baut das arm64-Image nach GHCR, Home Assistant zeigt das Update an. Datenbank-Migrationen laufen beim Start des Add-ons automatisch; steht eine an, sichert `serve.py` die Datenbank vorher als `app.db.<Zeitstempel>.bak` (die letzten drei bleiben).

**Lokal:** `uvicorn main:create_app --factory --reload` auf `localhost:8000`, Test am iPhone über die PC-IP im WLAN.

**Rechte des Add-ons:** Jedes Add-on läuft in einem abgeschotteten Container und darf von sich aus nicht mit Home Assistant sprechen. Zwei Schalter in `tellerplan/config.yaml` öffnen gezielt je einen Zugang. Gemeint ist die `config.yaml` des Add-ons, nicht die `configuration.yaml` von Home Assistant.

| Option | Öffnet den Zugang zu … | Wofür Tellerplan das braucht |
| --- | --- | --- |
| `hassio_api: true` | Supervisor-API (`http://supervisor/…`): Verwaltung von Apps, Backups und System | Die Einstellseite speichert über `POST /addons/self/options`, genau wie „Speichern“ im Reiter „Konfiguration“ |
| `homeassistant_api: true` | Home-Assistant-API (`http://supervisor/core/api/…`): Entitäten und Aktionen | Die Einkaufsliste ruft `todo.add_item` für die Bring-Liste auf |

Ist ein Schalter gesetzt, gibt der Supervisor dem Container beim Start einen Schlüssel als Umgebungsvariable `SUPERVISOR_TOKEN` mit. Tellerplan schickt ihn bei jeder Anfrage mit, und der Supervisor prüft, ob der Zugang laut `config.yaml` erlaubt ist. Ein Passwort oder ein selbst angelegter Token ist nicht nötig.

Wie viel das Add-on in der Supervisor-API darf, legt `hassio_role` fest. Ohne Angabe gilt `default`: Informationen lesen und die **eigenen** Optionen ändern, aber keine anderen Apps steuern und keine Backups anlegen. Das reicht für Tellerplan. `homeassistant_api` erlaubt dagegen grundsätzlich jede Aktion in Home Assistant; Tellerplan nutzt nur `todo.add_item`. Jeder der beiden Schalter senkt die Sicherheitsbewertung, die Home Assistant beim Add-on anzeigt. Das ist so vorgesehen.

## Vollbild-App

Festgelegt am 2026-10-25. Über Ingress läuft Tellerplan immer im Rahmen von Home Assistant (Kopfleiste, Menü). Für den Vollbildbetrieb auf dem iPhone ist Tellerplan zusätzlich direkt auf Port 8099 erreichbar und lässt sich in Safari mit „Zum Home-Bildschirm“ als eigenständige Web-App ablegen (`manifest.webmanifest`, Symbol `icon-180.png`).

**Anmeldung über Home Assistant statt eigener Passwörter.** Home Assistant bleibt das Tor: Tellerplan nutzt die OAuth-Anmeldung von Home Assistant (wie die Companion-App) mit PKCE und `state`.

1. Ohne Sitzung leitet jede Seite auf Port 8099 zu `/auth/login`, von dort zur Anmeldeseite von Home Assistant (`homeassistant_url`, leer = gleicher Host, Port 8123). `client_id` ist die Adresse, unter der das iPhone Tellerplan aufruft, z. B. `http://homeassistant.local:8099/`.
2. Home Assistant leitet mit einem Code zu `/auth/callback` zurück. Tellerplan prüft `state`, löst den Code serverseitig ein (im Add-on über `http://homeassistant:8123`) und erhält einen Refresh-Token.
3. Tellerplan legt eine Sitzung an (`web_session`, Migration 0009): im Cookie ein Zufallswert, in der Datenbank nur sein Hash, dazu Refresh-Token und `client_id`.
4. Alle 30 Minuten prüft Tellerplan mit dem Refresh-Token, ob der Zugang noch gilt. Hat Home Assistant ihn entzogen, endet die Sitzung; ist Home Assistant nicht erreichbar, gilt sie weiter.
5. „Abmelden“ in den Einstellungen entzieht den Zugang auch in Home Assistant (`/auth/revoke`).

Statische Dateien (CSS, JS, Manifest, Symbole) sind ohne Anmeldung abrufbar; die API unter `/api/…` verlangt weiter den Token. HTMX-Anfragen ohne Sitzung bekommen `HX-Redirect` zur Anmeldung. Eine Beschränkung auf bestimmte HA-Benutzer gibt es vorerst nicht (ein Benutzer).

**Unterwegs:** Ohne Nabu Casa nur über ein VPN zum Heimnetz (Tailscale-Add-on oder Router-VPN); vorerst ausgeklammert. HTTP im Heimnetz entspricht dem bisherigen Zugang zu Home Assistant; HTTPS wird spätestens für die Barcode-Kamera (Stufe 5) nötig.

## Ausbaustufen und offene Punkte

Fünf Stufen, jede einzeln nutzbar. Die Reihenfolge wurde am 2026-10-24 umgestellt: erst die Funktionen mit eigenen Daten (Lebensmittel, Rezepte, Plan, Tagebuch), danach die Importe.

1. **Kern:** Repo, Add-on-Gerüst, CI/Release, UI-Rahmen mit Tab-Leiste, Lebensmittel manuell und als Demo-Set, Nährwertrechnung
2. **Rezepte und Plan:** Rezept-Datenmodell, Rezeptliste im Ranking-Look, Rezept anlegen mit Zutaten aus den Lebensmitteln, Nährwerte pro Portion, 1–2-Wochenplan als Tagesliste
3. **Tagebuch:** vier Mahlzeiten, Tageslimit als Halbkreis und Makro-Balken, Übernahme aus dem Plan mit gegessenen Portionen
4. **Importe:** BLS-Import, Zeilenparser, Matching mit Alias-Lernen und Cookidoo-Sammlung am Rechner (erledigt 2026-10-25); offen: Freitext-Import, Kurzbefehl an die API
5. **Erweiterungen:** Chefkoch, Einfach Backen, Open-Food-Facts-Barcode, Gewicht per Kurzbefehl aus Apple Health

**Vor Stufe 4** (festgelegt am 2026-10-25)

- **Einkaufsliste** (erledigt, im Add-on noch zu testen): Der Knopf „🛒 Einkaufsliste“ im Plan sendet alle Zutaten der Planeinträge von heute bis heute + 13 Tage direkt an Bring und zeigt danach die Seite „Einkaufsliste“ mit dem Ergebnis. Modul `shopping`, nutzt `planner` und `recipes`, rechnet keine Nährwerte.
  - **Zusammenfassen:** Gleiche Artikel (gleicher Einkaufsname) werden je Einheit addiert, nicht in Gramm, weil „5 Stück“ beim Einkaufen mehr hilft als „290 g“: „2 Stück + 3 Stück“ → „5 Stück“, gemischt „1 Dose + 200 g“. Offene Zutaten erscheinen mit ihrem Originaltext; Artikel, die in allen Rezepten optional sind, tragen „optional“.
  - **Vorrat:** Stichwörter in `pantry_keywords` (Regel 6, einstellbar in HA und auf der Einstellseite). Ein Stichwort trifft das erste Wort des Lebensmittelnamens, wenn es damit endet (also nicht „Thunfisch in Öl“); deutsche Zusammensetzungen tragen das Grundwort hinten, also trifft „salz“ „Meersalz“, „zucker“ aber nicht „Zuckerschote“. Übersprungene Artikel zeigt die Seite einklappbar an.
  - **Name:** `food.shopping_name`, sonst aus dem BLS-Namen abgeleitet: Teil vor „, “ und „/“, ohne Gehaltsangaben („mind. 30 % Fett“) und ohne „roh“/„reif“ am Ende. „Karotte/Möhre, roh“ → „Karotte“.
  - **Senden:** Je Artikel `todo.add_item` über die Supervisor-API mit dem Namen als `item` und der Menge als `description` (in Bring die Spezifikation). Gesendet werden nur Planeinträge, die noch nicht gesendet wurden (`plan_entry.shopping_sent_at`); „Alles erneut senden“ schickt alle. Ziel-Liste ist `bring_list_entity` (z. B. `todo.furth`), Recht `homeassistant_api: true`. Tellerplan kennt kein Bring-Passwort. Lokal ohne Supervisor sendet der Knopf nichts; die Seite bietet die Liste zum Kopieren an.
- **Einstellseite** (erledigt, im Add-on noch zu testen): Tageslimit kcal, Eiweißziel sowie Fett- und KH-Ziel lassen sich in der App ändern, bisher geht das nur in Home Assistant unter Add-on → Konfiguration. Beim Speichern schreibt das Add-on seine eigenen Optionen über die Supervisor-API (`POST /addons/self/options`, dafür `hassio_api: true` in `config.yaml`) und lädt danach `settings` neu, ein Neustart ist nicht nötig. Lokal schreibt die Seite direkt in `dev/options.json`. `options.json` bleibt damit die einzige Quelle (Regel 6). Vergangene Tage zeigen danach das neue Ziel, denn Ziele werden nicht pro Tag gespeichert.
- **CI und Release prüfen:** CI läuft bei jedem Push erfolgreich. Der Release-Workflow lief noch nie, es gibt noch keinen Tag; der erste Tag `v0.1.0` muss also das arm64-Image bauen und nach GHCR legen.
- **Live-Betrieb auf dem Raspberry Pi:** Repository in Home Assistant hinzufügen, Add-on installieren, `api_token` setzen und Ingress auf dem iPhone testen. Port 8099 erst freigeben, wenn HTTPS geklärt ist (siehe unten).

**Offene Punkte**

- [x] Wie kommt die Einkaufsliste zu Bring? Über die Bring-Integration von Home Assistant mit `todo.add_item`, am 2026-10-25 von Hand getestet: Artikel und Spezifikation kommen in Bring an. Das Teilen-Menü ist damit nicht nötig.
- [ ] Kontrollseite vor dem Senden an Bring? Eine Seite mit allen Zutaten zum Abhaken: Vorratsartikel sind nicht angehakt, alle anderen schon; Mengen lassen sich anpassen, erst „Bestätigen“ schickt die Liste an Bring. Vorerst nicht umsetzen, sondern im Alltag prüfen, ob die direkte Übergabe reicht.
- [ ] Braucht die Einstellseite `hassio_api` wirklich? Laut Supervisor-Quellcode sind Aufrufe an `/addons/self/…` womöglich auch ohne erreichbar. Beim ersten Test im Add-on prüfen und den Schalter entfernen, falls er unnötig ist.
- [x] Vorratsliste: Stichwörter als Option `pantry_keywords` in `options.json` (z. B. „salz“ trifft alle Salz-Einträge aus BLS), einstellbar in HA und auf der Einstellseite. Kein Kennzeichen am Lebensmittel.
- [x] Artikelnamen: neues optionales Feld „Einkaufsname“ an `food` (z. B. „Hähnchenbrust“), gepflegt in der Lebensmittel-Ansicht, Migration 0006. Ohne Eintrag wird der Name aus dem BLS-Namen abgeleitet.

**Befunde der Projektprüfung vom 2026-10-25**

Konzept, nach Gewicht:

- [x] **K1 Einkaufsliste erneut senden:** Der Knopf sendete jedes Mal alle Zutaten der nächsten 14 Tage; Bring setzte schon Gekauftes wieder auf „zu kaufen“. *Behoben:* Jeder Planeintrag merkt sich `shopping_sent_at` (Migration 0008); gesendet werden nur neue Rezepte, und erst wenn alle Artikel ankommen. „Alles erneut senden“ auf der Seite Einkaufsliste schickt alle. Bleibt: Steht ein Artikel noch ungekauft in Bring, ersetzt ein neues Rezept mit demselben Artikel dessen Mengenangabe, statt sie zu addieren.
- [x] **K2 Vorrat trifft eingelegte Lebensmittel:** Geprüft wurde jedes Wort des BLS-Namens, daher fiel „Thunfisch in Öl“ als Vorrat weg. *Behoben:* Nur das erste Wort des Namens zählt (bei BLS das Lebensmittel selbst); offene Zeilen wie „1 TL Salz“ weiter Wort für Wort.
- [x] **K3 Sicherung beim Start:** Kopierte nur `app.db` ohne WAL-Datei und überschrieb bei jedem Start die einzige Kopie. *Behoben:* Gesichert wird nur, wenn eine Migration ansteht, mit der Backup-Funktion von SQLite (enthält die WAL-Daten), als `app.db.<Zeitstempel>.bak`; die letzten drei bleiben.
- [ ] **K4 HA-Sicherung „hot“:** Home Assistant kopiert `/data` bei laufender SQLite-Datenbank; die Kopie kann inkonsistent sein. Abhilfe: `backup_pre` mit Checkpoint oder `backup: cold`.
- [x] **K5 Zeitzone:** `date.today()` nutzte die Zeit des Containers. *Behoben:* Zentrale Uhr `clock.py` mit der Zeitzone aus `TZ` (setzt der Supervisor) und den Zeitzonendaten aus dem Paket `tzdata`; der Start schreibt Zeitzone und Datum ins Protokoll.
- [ ] **K6 Planportionen und „eingetragen“:** Ein Planeintrag gilt nach der ersten eingetragenen Portion als erledigt; Reste (Meal-Prep) bildet das Modell nicht ab. Nach dem Verschieben erscheint ein eingetragener Eintrag wieder als offen.
- [ ] **K7 Doku und Umsetzung:** Das Datenmodell nennt eine historisierte Tabelle `goal`, umgesetzt sind Ziele als Optionen (alte Tage zeigen das neue Ziel). Außerdem fehlen die Tabellen `ingredient_alias`, `weight`, `import_job` noch, und die Systemübersicht zeigt `shopping` nicht.
- [ ] **K8 Zwei Schreiber für die Optionen:** Eine Änderung in HA ohne Neustart geht verloren, wenn danach die Einstellseite speichert (letzter Schreiber gewinnt).
- [ ] **K9 Zutat ohne Einheit = Gramm:** „2 Eier“ ohne Einheit zählt als 2 g. Der Zeilenparser in Stufe 4 muss immer eine Einheit setzen.
- [ ] **K10 Einheiten-Schreibweisen:** Die Einkaufsliste addiert je Einheitstext; „EL“/„el“, „g“/„kg“, „Stück“/„Stk.“ bleiben getrennt.
- [ ] **K11 Zeiträume:** Der Plan zeigt bis heute + 14, die Einkaufsliste rechnet bis heute + 13.
- [x] **K12 Ingress-Port im internen Netz offen:** Andere Add-ons erreichten Port 8000 ohne Login. *Behoben mit der Vollbild-App:* Im Add-on nimmt Port 8000 nur Anfragen vom Ingress-Proxy `172.30.32.2` an; lokal ohne Supervisor bleibt er offen.
- [ ] **K13 Browser-Cache nach Updates:** CSS und JS ohne Version im Link; das iPhone kann alte Dateien behalten.
- [ ] **K14 Port 8099 nur HTTP:** siehe offener Punkt HTTPS unten.
- [ ] **K15 Snapshot mit vier Nährwerten:** Ballaststoffe, Zucker und Salz fehlen im Tagebuch-Snapshot und lassen sich für alte Tage nicht nachholen.

Code, nach Gewicht:

- [ ] **C-A Senden blockiert:** `send_to_todo_list` ruft Home Assistant nacheinander mit 10 s Timeout je Artikel auf; bei hängendem Supervisor bricht der Ingress-Proxy vorher ab.
- [x] **C-B Kaum Logging:** *Behoben:* Protokolliert werden Start (Zeitzone, Sicherung), jede Ablehnung durch den Supervisor, jedes Senden der Einkaufsliste mit Ergebnis und gespeicherte Optionen.
- [ ] **C-C Zwei Quellen für Optionen:** `settings.py` und `config.yaml` pflegen Optionen und Wertebereiche getrennt; kein Test prüft, ob sie übereinstimmen.
- [ ] **C-D Optionen nicht atomar geschrieben:** Abbruch beim Schreiben beschädigt `options.json`; schlägt das Schreiben nach dem Supervisor-Aufruf fehl, weichen HA und App voneinander ab.
- [ ] **C-E Netzwerk im Fachmodul:** `modules/shopping` importiert `supervisor` direkt; das Senden sollte hereingereicht werden.
- [x] **C-F Keine zentrale Uhr:** *Behoben mit K5:* alle Seiten nutzen `clock.today()`.
- [ ] **C-G Testlücken:** Offen: Datumsgrenzen in den Seiten, Coverage, echte Supervisor-Antworten. Erledigt: Migration 0007 auf befüllten Daten, Sicherung mit WAL.
- [ ] **C-H Kein CSRF-Schutz** für POST-Formulare (geringes Risiko, Ingress setzt eine HA-Sitzung voraus).
- [ ] **C-I Kleinigkeiten:** `add_entry` fällt bei 0 Portionen still auf den Standard zurück; `ShoppingItem.optional` hängt indirekt an `recipes`; Modul `options.py` vs. Route `/settings`. Erledigt: `supervisor` und `clock` in `known-first-party`.

Vor dem Tag `v0.1.0` behoben (2026-10-25): K1, K2, K3, K5, C-B, dazu C-F.

**Weitere offene Punkte**

- [ ] Einkaufshistorie aus REWE-Bestellungen nutzen (z. B. „was kaufe ich tatsächlich“, Mengen für die Einkaufsliste)? Vorerst nur als Todo; die Bestellseite enthält Telefonnummer, Bestellnummer und Abholdaten, `tools/rewe_har_extract.py` übernimmt davon nur Titel, EAN, Menge und Kategorie.
- [ ] Open Food Facts: einzelne Markenprodukte per Suche nach Name oder Barcode übernehmen (`source = off`, Barcode als Quell-ID), nicht die ganze Datenbank (mehrere Millionen Produkte, schwankende Qualität, ODbL). Vorschlag vom 2026-10-25, noch nicht umgesetzt.
- [ ] Konfigset für Grundzutaten exportieren/importieren (Namen, Standardprodukte über Quelle + Quell-ID), um sie am Rechner vorzubereiten.
- [ ] Liefern Chefkoch und Einfach Backen strukturierte Rezeptdaten? Vor Stufe 5 prüfen.
- [x] Welche Nährstoffe werden übernommen? Aus BLS die sieben vorhandenen Felder (kcal, Eiweiß, Fett, KH, Ballaststoffe, Zucker, Salz); weitere lassen sich aus der Excel-Datei nachziehen. Offen bleibt, welche davon die Oberfläche zeigt.
- [ ] HTTPS für die API auf Port 8099, vor dem Cookidoo-Kurzbefehl in Stufe 4: Bisher spricht der Port direkt HTTP, ein Token von unterwegs ginge unverschlüsselt. Optionen: Zertifikate von Home Assistant einbinden (`map: ssl` in `config.yaml`, uvicorn mit `/ssl/fullchain.pem` und `/ssl/privkey.pem`) oder Zugriff über einen vorhandenen Reverse Proxy. Ingress ist nicht betroffen, dort übernimmt Home Assistant HTTPS. Lokal bleibt HTTP; Browser-Funktionen wie Kamera (Barcode, Stufe 5) oder Bildschirm wach halten brauchen auf dem iPhone eine HTTPS-Verbindung, also Ingress.
- [ ] Kochschritte von Cookidoo übernehmen? Entschieden am 2026-10-25: im ersten Schritt nicht, zum Kochen genügt „In Cookidoo öffnen“. Später ergänzen (JSON-LD `recipeInstructions`, `tools/cookidoo_fetch.py`); dafür Regel 2 erweitern.
- [ ] Wie groß ist die Sammlung „Fürth“, und soll sie komplett oder schrittweise importiert werden?

## Quellen

- BLS 4.0, Lizenz CC BY 4.0, Herausgeber Max Rubner-Institut: https://blsdb.de/download
- Open Food Facts: https://world.openfoodfacts.org
