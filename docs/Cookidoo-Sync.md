# Cookidoo-Sync

Plan für Version **0.5.0**: Der Tellerplan-Plan und der Kalender „Meine Woche“ in Cookidoo gleichen sich ab. Grundlage ist der Wunsch vom 2026-10-28 in [[Architektur#Wünsche vom 2026-10-28]]; Stand der Recherche 2026-10-31.

## Ziel

Im Plan gibt es einen Knopf „Mit Cookidoo abgleichen“. Er zeigt zuerst eine Vorschau, was sich wo ändert, und übernimmt erst nach Bestätigung:

- Was in Cookidoo eingeplant ist, steht danach auch im Tellerplan (Einkaufsliste, Nährwerte, „Für heute geplant“).
- Was im Tellerplan mit Cookidoo-Rezept eingeplant ist, steht danach auch in Cookidoo (Thermomix, Cookidoo-App).
- Rezepte ohne Cookidoo-ID bleiben nur im Tellerplan.

## Recherche

**Schnittstelle:** die inoffizielle Bibliothek [`cookidoo-api`](https://github.com/miaucl/cookidoo-api) (MIT, Version 0.19.0 vom 2026-10-14, Python ≥ 3.12, Grundlage der Cookidoo-Integration in Home Assistant). Für den Kalender bietet sie:

| Funktion | Zweck |
| --- | --- |
| `get_recipes_in_calendar_week(day)` | Alle Tage der Woche, die `day` enthält, mit Rezepten (`id`, `name`, `url`); eigene Cookidoo-Rezepte nur als `customer_recipe_ids` |
| `add_recipes_to_calendar(day, recipe_ids)` | Rezepte an einem Tag einplanen |
| `remove_recipe_from_calendar(day, recipe_id)` | Rezept von einem Tag entfernen |

Verschieben gibt es nicht; es ist Entfernen + Einplanen. Portionen kennt der Cookidoo-Kalender nicht.

**Anmeldung:** OAuth2 mit PKCE gegen das Vorwerk-Konto, mit dem Zugang der Cookidoo-Android-App (`client_id` `mobile-android`, Rückleitung `com.vorwerk.cookidoo://code-grant`). In der veröffentlichten Version 0.19.0 gibt es dafür nur `login()`: Die Bibliothek füllt mit E-Mail und Passwort das Vorwerk-Formular selbst aus. Die Anmeldung über den Browser (`begin_login()`/`complete_login()`) steht bisher nur im Entwicklungsstand auf GitHub (geprüft 2026-10-31 an der installierten Version). Die Tokens (`access_token`, `refresh_token`, `expires_at`) lassen sich speichern (`save_token`/`load_token`) und erneuern sich selbst; ein Rückruf meldet neue Tokens.

**Technik:** asynchron auf `aiohttp`; weitere Abhängigkeiten `firebase-messaging`, `aiofiles`, `isodate`. Land und Sprache über `CookidooLocalizationConfig` (für Deutschland `de`, `de-DE`, `https://cookidoo.de/foundation/de-DE`).

**Home-Assistant-Integration „Cookidoo“:** hat einen Kalender, der ist aber **nur lesbar** und liefert je Tag nur den Rezeptnamen, keine ID. Zum Lesen über Home Assistant (ohne eigene Zugangsdaten) taugt er also nur mit Abgleich über den Titel, zum Schreiben gar nicht. Daher spricht Tellerplan Cookidoo direkt an.

**Risiken**

- Inoffiziell: Vorwerk kann die Schnittstelle oder die Anmeldung jederzeit ändern (Captcha, Zwei-Faktor). Der Sync ist darum eine Zusatzfunktion; fällt er aus, funktioniert der Plan weiter, und die Seite zeigt eine verständliche Meldung.
- Größere Abhängigkeiten im Image: `cryptography`, `protobuf`, `firebase-messaging` (für die Thermomix-Fernüberwachung der Bibliothek, vom Kalender nicht gebraucht, aber nicht abwählbar).
- Die Tokens liegen in `/data` und sind Teil der HA-Backups; ein Passwort speichert Tellerplan nicht.
- Die Anmeldung borgt sich den Zugang der Android-App. Ändert Vorwerk den, ist eine neue Version der Bibliothek nötig.

## Abgleichsregeln

Abgeglichen wird **ab heute** bis zum Ende des Plans (heute + 14 Tage, wie die Planseite: `FUTURE_DAYS`); vergangene Tage bleiben unberührt. Wird ein abgeglichener Eintrag in Tellerplan in die Vergangenheit verschoben, bleibt er dort und wird nicht mehr abgeglichen. Schlüssel ist die Cookidoo-ID: `recipe.source = "cookidoo"` und `recipe.source_id` (z. B. `r753850`) gleich `id` im Kalender.

Damit der Abgleich unterscheiden kann, *wer* etwas geändert hat, merkt sich jeder Planeintrag, an welchem Tag er zuletzt in Cookidoo stand (`plan_entry.cookidoo_day`, die gemeinsame Basis). Löscht man in Tellerplan einen abgeglichenen Eintrag, bleibt eine kleine Notiz „in Cookidoo entfernen“ (`cookidoo_removal`), die der nächste Abgleich abarbeitet und löscht. Mehr wird nicht gespeichert.

| Cookidoo | Tellerplan | Basis (`cookidoo_day`) | Ergebnis |
| --- | --- | --- | --- |
| Tag X | Tag X | egal | nichts zu tun, Basis = X |
| Tag X | – | leer (nie abgeglichen) | Tellerplan: neu an X mit Standardportionen |
| – | Tag X | leer | Cookidoo: an X einplanen |
| Tag X | Tag Y | Y (Tellerplan unverändert) | Cookidoo hat verschoben → Tellerplan nach X |
| Tag X | Tag Y | X (Cookidoo unverändert) | Tellerplan hat verschoben → Cookidoo nach Y |
| Tag X | Tag Y | Z (beide verschoben) | Cookidoo gewinnt → Tellerplan nach X |
| – | Tag X | gesetzt | in Cookidoo entfernt → in Tellerplan löschen |
| Tag X | – (Notiz `cookidoo_removal`) | – | in Tellerplan gelöscht → in Cookidoo entfernen |
| Rezept unbekannt | – | – | Platzhalter-Rezept (Titel, ID, Link) anlegen und an X einplanen; danach von der Rezeptseite füllen (Schritt 6b) |
| – | Rezept ohne Cookidoo-ID | – | bleibt nur im Tellerplan |
| Tag X | Tag in der Vergangenheit | X | in Tellerplan zurückgelegt (nicht gekocht) → in Cookidoo entfernen, Basis leeren |
| Tag X | Tag nach dem Planende | X | Tellerplan hat verschoben → in Cookidoo verschieben (nach dem Zeitraum darf geschrieben werden) |
| Tag X | Tag Y | leer | zwei verschiedene Mahlzeiten → in beide Richtungen ergänzen (nicht als Verschiebung raten, damit nichts verloren geht) |
| – | Tag X | in der Vergangenheit | gilt als neu → in Cookidoo einplanen |
| Notiz nach dem Planende | | | bleibt liegen (dort ist der Kalender nicht gelesen); Notizen in der Vergangenheit werden gelöscht |

Steht dasselbe Rezept mehrmals im Zeitraum, werden zuerst gleiche Tage gepaart, dann Einträge, deren Basis in Cookidoo noch belegt ist; übrige abgeglichene Einträge folgen dem Cookidoo-Tag, der ihrer Basis am nächsten liegt. Portionen ändert der Abgleich nie. Der Abgleich ist stabil: Nach dem Übernehmen findet ein zweiter Lauf nichts mehr (getestet für jede Regel).

## Entscheidungen (2026-10-31)

1. **Anmeldung über OAuth**, ohne Passwort in den Optionen; gespeichert werden nur die Tokens, danach hält sich der Zugang über das Refresh-Token selbst. Nach Schritt 1 wird es die *einmalige Eingabe*; der Browser-Weg kommt dazu, sobald die Bibliothek ihn veröffentlicht.
   - *Einmalige Eingabe:* In Tellerplan unter „Cookidoo verbinden“ E-Mail und Passwort eingeben; sie gehen nur an `login()` und werden nicht gespeichert. Geht mit 0.19.0.
   - *Browser:* Ein Link öffnet die Vorwerk-Anmeldung, die Rückleitung `com.vorwerk.cookidoo://code-grant?code=…` (kann der Browser nicht öffnen) wird kopiert und eingefügt. Braucht eine neuere Version der Bibliothek.
2. **Immer einplanen**, auch wenn der Cookidoo-Tag schon Rezepte hat.
3. **In Cookidoo entfernt → in Tellerplan löschen**; die Vorschau zeigt es vorher an.
4. **Unbekannte Cookidoo-Rezepte als Platzhalter** (seit Schritt 6b nur noch Zwischenstand und Rückfall, siehe dort): Tellerplan legt ein Rezept nur mit Titel, Cookidoo-ID und Link an (`source = cookidoo`, ohne Zutaten, Standardportionen 1 bis zur Pflege) und plant es ein. Im Plan zeigt der Eintrag den Link „In Cookidoo öffnen“, damit klar ist, welches Rezept gemeint ist. Das entspricht Regel 2 (Titel, Link, ID, keine Nährwerte). Ein späterer Import der Sammlung ergänzt die Zutaten, weil er dasselbe Rezept an Quelle und ID erkennt (dafür muss der Import erweitert werden, siehe Schritt 3).
5. **Nur auf Knopfdruck**, kein zyklischer Abgleich.
6. **Land und Sprache als feste Option** `cookidoo_locale` (Vorgabe `de-DE`, Land wird daraus abgeleitet).

## Umsetzung in Schritten

Jeder Schritt ist für sich lauffähig, mit Tests, und darf als 0.4.x erscheinen. 0.5.0 wird erst gesetzt, wenn der Test auf dem Pi vollständig abgeschlossen ist (Vorgabe 2026-11-02).

### Schritt 1: Erkundung am Rechner

Skript `tools/cookidoo_probe.py` (Anleitung im Kopf der Datei), Zugang und Ausgaben in `dev/cookidoo/` (nicht im Git).

- [x] `login`: Anmeldung mit einmaliger Eingabe klappt ohne Captcha oder Zwei-Faktor; der Zugang über die gespeicherten Tokens läuft stabil (2026-10-31).
- [ ] `login --browser`: erst, wenn eine Version mit `begin_login` erschienen ist.
- [x] `week`: IDs haben das Format von `recipe.source_id` (`r821223`), Links die Form `https://cookidoo.de/recipes/recipe/de-DE/r821223`. **Tage ohne Rezepte fehlen in der Antwort** – der Abgleich wertet einen fehlenden Tag als leer. `title` eines Tages ist das Datum („02.11.2026“), nicht der Rezeptname. Die Wochen beginnen am Montag (gelesen ab Samstag 31.10.; die zweite Woche begann mit Montag 02.11.).
- [x] `roundtrip`, `add`, `remove`: Einplanen und Entfernen wirken sofort und sind in der Cookidoo-App sichtbar.
- [x] `refresh`: Token erneuern klappt. Offen zu beobachten: Hält das Refresh-Token auch nach mehreren Tagen ohne Nutzung? (einfach in einer Woche erneut `week`)
- [x] Abhängigkeiten für arm64 und Python 3.14 (2026-10-31, per `pip download` für `manylinux_aarch64`, cp314): fertige Wheels für aiohttp, cryptography, protobuf, cffi, yarl, multidict, frozenlist, propcache; `http_ece` gibt es nur als Quellpaket, ist aber reines Python. Kein Compiler im Image nötig. Der echte Bau läuft in Schritt 2 über die CI.
- [x] Ergebnisse eingetragen (2026-10-31).

### Schritt 2: Optionen und Anbindung

- [x] Option `cookidoo_locale` (Vorgabe `de-DE`, Muster `xx-XX`) in `config.yaml`, `settings.py`, `options.example.json`, `DOCS.md`.
- [x] `cookidoo-api==0.19.0` in `requirements.txt` des Add-ons.
- [x] Anmeldung in Tellerplan: Einstellungen → Cookidoo mit E-Mail und Passwort (einmalig, nicht gespeichert), danach „Verbunden als …“ und „Trennen“. Den Browser-Weg ergänzen, sobald die Bibliothek ihn veröffentlicht. Ohne Verbindung kein Knopf im Plan (Schritt 6).
- [x] `app/cookidoo.py` neben `supervisor.py`: einzige Stelle mit Netzwerkaufrufen an Cookidoo. Kapselt die asynchrone Bibliothek in einfache Funktionen (`read_calendar(first, last)`, `plan(day, ids)`, `unplan(day, id)`), Tokens und Anzeigename in `cookidoo_token.json` neben der Datenbank (Rechte 600, bei jeder Erneuerung gespeichert), 30 s Zeitüberschreitung, verständliche Fehler (`CookidooError`, `NotConnectedError`). Tokens nie ins Log. Eigene Cookidoo-Rezepte liefert der Kalender nur als ID ohne Namen; `read_calendar` lässt sie aus.
- [x] Tests ersetzen die Bibliothek per `monkeypatch` durch eine Attrappe (wie bei `supervisor.py`); kein Netzwerk in CI.
- [x] Image-Bau für arm64 über die CI und Verbinden auf dem Pi (0.4.6, 2026-10-31).
- [x] „Verbindung prüfen“ in Einstellungen → Cookidoo: liest die nächsten 14 Tage aus „Meine Woche“ und listet sie, ohne etwas zu ändern (0.4.7). Damit auf dem Pi prüfen:
  - [x] Liste stimmt mit der Cookidoo-App überein
  - [x] nach ein bis zwei Tagen ohne neue Anmeldung noch lesbar (Token-Erneuerung im Add-on, geprüft 2026-11-02)
  - [x] nach Neustart des Add-ons weiter verbunden

### Schritt 3: Datenmodell und Platzhalter

- [x] Migration 0015: `plan_entry.cookidoo_day` (Datum, leer = nie abgeglichen) und Tabelle `cookidoo_removal` (`day`, `cookidoo_id`).
- [x] `planner.delete_entry`: bei gesetztem `cookidoo_day` eine Notiz `cookidoo_removal` anlegen; `move_entry` lässt `cookidoo_day` stehen (daran erkennt der Abgleich die Verschiebung).
- [x] Rezept löschen: Planeinträge vorher über `planner.delete_entry` entfernen statt per `ON DELETE CASCADE`, damit auch dann die Notizen entstehen (sonst käme das Rezept beim nächsten Abgleich als Platzhalter zurück).
- [x] `recipes`: Platzhalter-Rezept anlegen (Titel, Cookidoo-ID, Link, 1 Portion), erkennbar daran, dass es keine Zutaten hat.
- [x] **Rezept ohne Zutaten gilt als unvollständig** (bisher „0 von 0“ = vollständig). Sonst stünde ein Platzhalter mit 0 kcal im Plan, und ein Tagebucheintrag zählte 0 kcal ohne den Hinweis „eher zu niedrig“.
- [x] **Import ergänzt Zutaten eines vorhandenen Rezepts ohne Zutaten.** Bisher fügt `import_document` Zutatenzeilen nur bei neuen Rezepten ein; ein Platzhalter bliebe sonst leer.
- [x] Rezeptliste und Rezeptseite: Platzhalter mit Kennzeichen „Platzhalter“ und Link „In Cookidoo öffnen“ (vorhandener Knopf zur Quelle); im Ranking hinten ohne Score (galt schon für Rezepte ohne zugeordnete Zutaten).
- [x] Tests für alles (`tests/test_cookidoo_model.py`).
- [x] Rezept nur mit „nach Bedarf“-Zeilen (Salz, Pfeffer) bleibt vollständig; unvollständig ist nur ein Rezept ganz ohne Zeilen (`MatchStatus.empty`).
- [ ] Test auf dem Pi: Migration 0015 läuft (0.4.8), Rezepte und Plan unverändert.

### Schritt 4: Abgleich als reine Logik

- [x] `modules/planner/cookidoo_sync.py`: `plan_sync(first, last, planned, calendar, notes, known_ids)` liefert einen `SyncPlan` mit Änderungen (`AddToTellerplan`, `MoveInTellerplan`, `DeleteFromTellerplan`, `AddToCookidoo`, `MoveInCookidoo`, `RemoveFromCookidoo`; intern `MarkSynced`, `DropNote`). Kein Netzwerk, keine Datenbank; eigene Eingabetypen statt `cookidoo.CalendarRecipe`, damit das Modul nichts von der Anbindung weiß.
- [x] Tabellengetriebene Tests für jede Zeile der Abgleichsregeln, dazu doppelte Rezepte, Vergangenheit, nach dem Planende, Notizen (`tests/test_cookidoo_sync.py`).
- [x] Stabilität: Jeder Fall wird nachgespielt und erneut abgeglichen; der zweite Lauf findet nichts.
- [x] Modulgrenzen: Das Modul importiert nichts aus anderen Fachmodulen; Regel 7 bleibt unverändert.
- Hinweis für Schritt 5: Steht ein unbekanntes Rezept mehrmals im Kalender, kommen mehrere `AddToTellerplan` mit `placeholder=True` – der Platzhalter darf nur einmal angelegt werden.

### Schritt 5: Übernehmen

- [x] `modules/planner/cookidoo_apply.py`: `preview` (liest, schreibt nichts) und `apply` (liest neu, schreibt nur, wenn die Vorschau noch stimmt – Kennung `fingerprint`). Cookidoo über die Schnittstelle `CookidooCalendar` (erfüllt von `CookidooAccount`).
- [x] Erst alle Schreibzugriffe auf Cookidoo, dann Tellerplan; festgeschrieben wird in einer Transaktion vom Aufrufer.
- [x] Nach dem ersten Fehler von Cookidoo wird dort nichts mehr geschrieben; Änderungen in Tellerplan werden trotzdem übernommen. Der Rest kommt beim nächsten Abgleich.
- [x] Verschieben in Cookidoo: erst am neuen Tag einplanen, dann am alten entfernen; scheitert das Entfernen, bleibt eine Notiz. Notizen verschwinden erst nach erfolgreichem Entfernen (`RemoveFromCookidoo.note_id`).
- [x] Unbekanntes Rezept mehrmals im Kalender → ein Platzhalter. In Cookidoo entfernt → in Tellerplan löschen ohne neue Notiz.
- [x] Tests mit einer Kalender-Attrappe (`tests/test_cookidoo_apply.py`), auch für Fehler mitten im Abgleich.

### Schritt 6: Oberfläche

- [x] Im Plan oben „⇄ Cookidoo“, nur wenn verbunden.
- [x] Vorschau `/plan/cookidoo`: Änderungen gruppiert nach „In Tellerplan“, „Neue Platzhalter“, „In Cookidoo“; „Übernehmen“ und „Abbrechen“. Nichts zu tun → „Alles abgeglichen“. Hat sich Cookidoo seit der Vorschau geändert, kommt die neue Vorschau mit Hinweis.
- [x] Planeintrag mit Cookidoo-Rezept zeigt „In Cookidoo öffnen ↗“, Platzhalter zusätzlich das Kennzeichen.
- [x] Ergebnis als Meldung im Plan; Fehler mit Verweis auf Einstellungen → Cookidoo.
- [x] Tests (`tests/test_cookidoo_pages.py`).
- [x] Test auf dem Pi (0.4.9): bekannte Rezepte übernommen, unbekannte als Platzhalter angelegt (2026-11-02).
- [x] Befund danach: Platzhalter waren mit 1 Portion eingeplant und blieben das auch nach dem Import (Plan und Einkaufsliste zu klein). Behoben: Füllt der Import einen Platzhalter, übernehmen dessen Planeinträge die neuen Standardportionen, sofern sie noch auf den alten stehen. Der Import meldet die gefüllten Platzhalter (`ImportResult.filled`), die Import-Seite setzt die Portionen über den Plan (Regel 7). Ablauf in [[Datenpflege#Platzhalter aus „Meine Woche“ füllen]].

### Schritt 6b: Unbekannte Rezepte sofort laden (Wunsch vom 2026-11-03)

Die Cookidoo-ID reicht, um ein Rezept zu laden; der umständliche Weg über `tools/cookidoo_fetch.py` am Rechner entfällt für Rezepte aus „Meine Woche“.

**Ablauf:** Der Abgleich bleibt unverändert und legt in seiner Transaktion Platzhalter an (`SyncResult.placeholders`). Nach dem Festschreiben holt die Plan-Seite deren Rezeptseiten und füllt sie über den normalen Import; Planeinträge bekommen dabei die Standardportionen der Seite. Scheitert ein Abruf, bleibt der Platzhalter – nichts geht verloren, und der Abgleich ist schon gespeichert.

- [x] `modules/importers/cookidoo_page.py`: Rezeptseite → Entwurf, reine Logik (JSON-LD `schema.org/Recipe` wie im Tool, damit Zeilenformat und gelernte Zuordnungen gleich bleiben). Titel, Portionen aus `recipeYield`, Gesamtzeit, Zutatenzeilen; `nutrition` (pro Portion) nur als Vergleichswert (Regel 2). Texte gekürzt, höchstens 100 Zeilen. Kategorie wird nicht übernommen (Cookidoo-Kategorien passen nicht zur eigenen Auswahl).
- [x] `cookidoo.py`: `recipe_page(id)` ohne Anmeldung von der öffentlichen Seite; Link nur aus der geprüften ID, keine Weiterleitungen, höchstens 2 MB, 30 s. Seite fehlt (z. B. 404) → `RecipePageMissingError`, sonst `CookidooError`.
- [x] `web/cookidoo_fill.py`: führt Abruf, Titelprüfung, Import und Portionen zusammen (nur hier, Regel 7). Gedrosselt (1 s zwischen den Seiten), höchstens 10 Seiten je Lauf. Seite fehlt oder Titel passt nicht → überspringen, weiter; Cookidoo nicht erreichbar → abbrechen.
- [x] **Titelprüfung:** Der Titel der Seite muss zum Titel aus dem Kalender passen (ohne Groß-/Kleinschreibung, Satzzeichen, Leerraum). Sonst bleibt der Platzhalter, und der Grund wird gezeigt.
- [x] Vorschau: Gruppe „Neue Rezepte“ statt „Neue Platzhalter“. Meldung im Plan: „N neue Rezepte aus Cookidoo geladen“ mit Link zum Zuordnen, ggf. „M bleiben vorerst Platzhalter“.
- [x] Einstellungen → Importieren: „Platzhalter füllen“ (nur verbunden und wenn es Platzhalter gibt) für alle vorhandenen Platzhalter, mit Grund je übersprungenem Rezept.
- [x] Tests: `test_cookidoo_page.py`, `test_cookidoo_fill.py`, Abruf in `test_cookidoo.py`. Am Rechner gegen die echte Seite geprüft (r821223: 15 Zeilen, 4 Portionen, 430 kcal Vergleich; r1: 404).
- [ ] Test auf dem Pi: siehe Punkte 11–13 unten.

### Test auf dem Pi (0.4.9)

Am besten mit einem Rezept an einem Tag in der nächsten Woche, das sonst nirgends geplant ist.

1. [ ] Plan → „⇄ Cookidoo“: Die Vorschau zeigt, was in „Meine Woche“ steht und Tellerplan noch nicht hat (bekannte Rezepte unter „In Tellerplan“, unbekannte unter „Neue Platzhalter“), und umgekehrt unter „In Cookidoo“. Stimmt das mit der Cookidoo-App?
2. [ ] „Übernehmen“: Meldung im Plan, Einträge stehen an den richtigen Tagen; in der Cookidoo-App stehen die Tellerplan-Rezepte.
3. [ ] Sofort erneut „⇄ Cookidoo“ → „Alles abgeglichen“.
4. [ ] In der Cookidoo-App ein Rezept auf einen anderen Tag verschieben → Abgleich verschiebt es in Tellerplan.
5. [ ] In Tellerplan ein abgeglichenes Rezept verschieben → Abgleich verschiebt es in Cookidoo (am alten Tag weg, am neuen da).
6. [ ] In Tellerplan ein abgeglichenes Rezept entfernen → Abgleich entfernt es in Cookidoo.
7. [ ] In der Cookidoo-App ein Rezept entfernen → Abgleich entfernt es in Tellerplan.
8. [ ] Platzhalter: Kennzeichen im Plan und in der Rezeptliste, „In Cookidoo öffnen“ führt zum richtigen Rezept; Tagebuch zeigt bei einem gegessenen Platzhalter den Hinweis „eher zu niedrig“.
9. [ ] Vorschau öffnen, in der Cookidoo-App etwas ändern, dann „Übernehmen“ → Hinweis und neue Vorschau, nichts geschrieben.
10. [ ] Am iPhone: Knopf, Vorschau und Meldungen gut bedienbar.
11. [ ] Schritt 6b: Unbekanntes Rezept in Cookidoo einplanen → Vorschau zeigt es unter „Neue Rezepte“; nach „Übernehmen“ steht es mit Zutatenzeilen und Standardportionen der Seite im Plan, Meldung „1 neues Rezept aus Cookidoo geladen“.
12. [ ] Vorhandene Platzhalter (aus 0.4.9): Einstellungen → Importieren → „Platzhalter füllen“; Planeinträge bekommen die Standardportionen.
13. [ ] Zuordnen der neuen Zutaten; danach rechnet das Rezept, Einkaufsliste mit richtigen Mengen.

Erst wenn alle Punkte erledigt sind: Schritt 7 und Version 0.5.0.

### Schritt 7: Doku und Release 0.5.0

- [ ] [[Architektur]]: Zeile „Cookidoo-Planung“ in der Entscheidungstabelle ablösen, Wunsch abhaken, Verweis hierher.
- [ ] `DOCS.md`: Optionen und Hinweis auf die inoffizielle Schnittstelle.
- [ ] [[Start]]: Punkt abhaken.
- [ ] `version` auf 0.5.0, `git push --atomic origin main v0.5.0`, Action abwarten, dann in Home Assistant aktualisieren.

## Neubewertung (2026-11-02)

Stand: Schritte 1 und 2 fertig, Anmeldung und Lesen laufen stabil auf dem Pi, auch nach Neustart und über mehrere Tage. Beim Durchsehen des Codes für Schritt 3 fielen zwei Lücken auf, die jetzt in Schritt 3 stehen:

1. Ein Rezept ohne Zutaten gilt bisher als vollständig – Platzhalter würden als „0 kcal, vollständig“ gerechnet.
2. Der Sammlungsimport ergänzt bei vorhandenen Rezepten keine Zutaten – Platzhalter blieben dauerhaft leer.

Dazu ergänzt: Löschen eines Rezepts muss Notizen hinterlassen; „Übernehmen“ rechnet mit frischen Daten neu; Zeitraum = Planseite (heute + 14 Tage).

**Zuschnitt der Releases:**

| Version | Inhalt | Auf dem Pi sichtbar |
| --- | --- | --- |
| 0.4.8 | Schritt 3 (Migration 0015, Platzhalter, Vollständigkeit, Import) | Platzhalter-Kennzeichen; Migration läuft, Datensicherung vorher |
| – | Schritt 4 (reine Logik), nur Commit | nichts |
| 0.4.x | Schritte 5–6, Sicherheitsprüfung | Knopf „Mit Cookidoo abgleichen“ mit Vorschau – Test auf dem Pi |
| 0.5.0 | Schritt 7, **erst wenn der Test auf dem Pi vollständig abgeschlossen ist** | – |

## Sicherheitsprüfung der Bibliothek

`cookidoo-api` ist reiner Python-Quelltext (Version 0.19.0, rund 6.200 Zeilen, davon gut 3.000 in `cookidoo.py`), installiert unter `tellerplan/app/.venv/Lib/site-packages/cookidoo_api/`. Vor Release 0.5.0 und bei jedem Versionswechsel durchgehen, Ergebnis hier festhalten:

Die Bibliothek und ihre Abhängigkeiten laufen im Prozess des Add-ons und hätten damit Zugriff auf `/data` (Datenbank, Cookidoo-Tokens) und den `SUPERVISOR_TOKEN` (Aktionen in Home Assistant). Darum diese Prüfung, zu erledigen vor 0.5.0, parallel zum Test auf dem Pi.

- [ ] **Wohin Daten gehen:** nur Vorwerk-Adressen (`*.vorwerk-digital.com`, `cookidoo.<land>`)? Baut `remote_monitoring.py` (Firebase) schon beim Import Verbindungen auf?
- [ ] **Zugangsdaten:** Passwort und Tokens nie in Logs, Fehlermeldungen oder Dateien der Bibliothek (Tellerplan schreibt die Tokens selbst)?
- [ ] **Anmeldung:** `state` und PKCE geprüft, Zertifikatsprüfung aktiv (kein `ssl=False`), Bedeutung von `CookieJar(unsafe=True)`, nur Weiterleitungen zu Vorwerk-Adressen (`_assert_ciam_origin`)?
- [ ] **Antworten von Cookidoo:** nur gelesen, nie ausgeführt, nachgeladen oder als Dateipfad benutzt? Folgen der Endpunkt-Erkennung (`well_known.py`) nur Vorwerk-Adressen?
  - [x] In Tellerplan (2026-11-02, 0.4.9): Antworten gelten als nicht vertrauenswürdig. `cookidoo.py` übernimmt nur IDs der Form `r123`, Links nur per https auf die Cookidoo-Seite des Landes (sonst aus der ID gebaut) und kürzt Namen. Alle externen Links in den Vorlagen laufen zusätzlich durch den Filter `external_url` (nur http/https). Anlass: Ein `javascript:`-Link aus einer Antwort wäre sonst als `href` im Plan gelandet; über Ingress läuft Tellerplan unter der Adresse von Home Assistant.
  - [ ] In der Bibliothek selbst: offen.
- [ ] **Import:** kein Code mit Nebenwirkungen beim `import`, keine Hintergrund-Aufgaben, nichts wird nachinstalliert.
- [ ] **Abhängigkeiten:** `pip-audit` gegen die tatsächlich installierten Versionen (aiohttp, cryptography, protobuf, firebase-messaging …).
- [ ] **Festschreiben:** alle Pakete des Images mit Version und Prüfsumme (`pip install --require-hashes`), damit `~=`-Angaben der Bibliothek nicht still neuere Versionen holen. Entscheiden, ob sich der Aufwand lohnt.

## Später

- Einkaufsliste wahlweise an Cookidoo statt an Bring (`add_ingredient_items_for_recipes`)
