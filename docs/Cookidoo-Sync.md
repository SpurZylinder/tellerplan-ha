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

Abgeglichen wird **ab heute** bis zum Ende des Plans; vergangene Tage bleiben unberührt. Schlüssel ist die Cookidoo-ID: `recipe.source = "cookidoo"` und `recipe.source_id` (z. B. `r753850`) gleich `id` im Kalender.

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
| Rezept unbekannt | – | – | Platzhalter-Rezept (Titel, ID, Link) anlegen und an X einplanen |
| – | Rezept ohne Cookidoo-ID | – | bleibt nur im Tellerplan |

Steht dasselbe Rezept mehrmals im Zeitraum, werden die Einträge nach dem nächstgelegenen Tag paarweise zugeordnet. Portionen ändert der Abgleich nie.

## Entscheidungen (2026-10-31)

1. **Anmeldung über OAuth**, ohne Passwort in den Optionen; gespeichert werden nur die Tokens, danach hält sich der Zugang über das Refresh-Token selbst. Nach Schritt 1 wird es die *einmalige Eingabe*; der Browser-Weg kommt dazu, sobald die Bibliothek ihn veröffentlicht.
   - *Einmalige Eingabe:* In Tellerplan unter „Cookidoo verbinden“ E-Mail und Passwort eingeben; sie gehen nur an `login()` und werden nicht gespeichert. Geht mit 0.19.0.
   - *Browser:* Ein Link öffnet die Vorwerk-Anmeldung, die Rückleitung `com.vorwerk.cookidoo://code-grant?code=…` (kann der Browser nicht öffnen) wird kopiert und eingefügt. Braucht eine neuere Version der Bibliothek.
2. **Immer einplanen**, auch wenn der Cookidoo-Tag schon Rezepte hat.
3. **In Cookidoo entfernt → in Tellerplan löschen**; die Vorschau zeigt es vorher an.
4. **Unbekannte Cookidoo-Rezepte als Platzhalter:** Tellerplan legt ein Rezept nur mit Titel, Cookidoo-ID und Link an (`source = cookidoo`, ohne Zutaten, Standardportionen 1 bis zur Pflege) und plant es ein. Im Plan zeigt der Eintrag den Link „In Cookidoo öffnen“, damit klar ist, welches Rezept gemeint ist. Das entspricht Regel 2 (Titel, Link, ID, keine Nährwerte). Ein späterer Import der Sammlung ergänzt die Zutaten, weil er dasselbe Rezept an Quelle und ID erkennt.
5. **Nur auf Knopfdruck**, kein zyklischer Abgleich.
6. **Land und Sprache als feste Option** `cookidoo_locale` (Vorgabe `de-DE`, Land wird daraus abgeleitet).

## Umsetzung in Schritten

Jeder Schritt ist für sich lauffähig, mit Tests, und darf als 0.4.x erscheinen; 0.5.0 ist der Stand nach Schritt 7.

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

- [ ] Option `cookidoo_locale` in `config.yaml` (options + schema), `settings.py`, `options.example.json`, `DOCS.md`.
- [ ] Anmeldung in Tellerplan: Einstellungen → „Cookidoo verbinden“ zeigt den Anmelde-Link und ein Feld für die Rückleitung; „Trennen“ löscht die Tokens. Ohne Verbindung kein Knopf im Plan.
- [ ] `app/cookidoo.py` neben `supervisor.py`: einzige Stelle mit Netzwerkaufrufen an Cookidoo. Kapselt die asynchrone Bibliothek in einfache Funktionen (`read_calendar(first, last)`, `plan(day, ids)`, `unplan(day, id)`), Tokens in `/data/cookidoo_token.json` (bei jeder Erneuerung gespeichert), Zeitüberschreitungen und verständliche Fehler (`CookidooError`). Tokens nie ins Log.
- [ ] Schnittstelle als `Protocol`, damit Tests eine Attrappe nutzen; kein Netzwerk in CI.

### Schritt 3: Datenmodell

- [ ] Migration 0015: `plan_entry.cookidoo_day` (Datum, leer = nie abgeglichen) und Tabelle `cookidoo_removal` (`day`, `cookidoo_id`).
- [ ] `recipes`: Platzhalter-Rezept anlegen (Titel, Cookidoo-ID, Link), erkennbar daran, dass es keine Zutaten hat; der Sammlungsimport ergänzt es später.
- [ ] `planner.delete_entry`: bei gesetztem `cookidoo_day` eine Notiz `cookidoo_removal` anlegen; `move_entry` lässt `cookidoo_day` stehen (daran erkennt der Abgleich die Verschiebung).
- [ ] Tests für beides.

### Schritt 4: Abgleich als reine Logik

- [ ] `modules/planner/cookidoo_sync.py`: nimmt Planeinträge, Kalendereinträge und Notizen und liefert eine Liste von Änderungen (`SyncChange`: Tellerplan neu/verschieben/löschen, Cookidoo einplanen/entfernen, unbekanntes Rezept). Kein Netzwerk, keine Datenbank-Schreibzugriffe.
- [ ] Tabellengetriebene Tests für jede Zeile der Abgleichsregeln, dazu doppelte Rezepte und Tage ohne Einträge.
- [ ] Modulgrenzen: `planner` darf `recipes` lesen; Regel 7 bleibt unverändert.

### Schritt 5: Übernehmen

- [ ] Änderungen ausführen: zuerst Cookidoo (kann scheitern), dann Tellerplan in einer Transaktion, danach `cookidoo_day` setzen und erledigte Notizen löschen.
- [ ] Teilweise Fehler: was in Cookidoo geklappt hat, wird übernommen; der Rest erscheint als Meldung und beim nächsten Abgleich erneut.
- [ ] Tests mit der Attrappe, auch für Abbruch mitten im Abgleich.

### Schritt 6: Oberfläche

- [ ] Im Plan oben „Mit Cookidoo abgleichen“ (nur mit Zugangsdaten).
- [ ] Vorschau-Seite: Änderungen gruppiert nach „In Tellerplan“, „In Cookidoo“ und „Neue Platzhalter“; Knöpfe „Übernehmen“ und „Abbrechen“. Nichts zu tun → „Alles abgeglichen“.
- [ ] Planeintrag mit Cookidoo-Rezept zeigt „In Cookidoo öffnen“, Platzhalter zusätzlich ein Kennzeichen.
- [ ] Ergebnis als Meldung im Plan; Fehler der Anmeldung mit Hinweis auf die Optionen.
- [ ] Am iPhone prüfen.

### Schritt 7: Doku und Release 0.5.0

- [ ] [[Architektur]]: Zeile „Cookidoo-Planung“ in der Entscheidungstabelle ablösen, Wunsch abhaken, Verweis hierher.
- [ ] `DOCS.md`: Optionen und Hinweis auf die inoffizielle Schnittstelle.
- [ ] [[Start]]: Punkt abhaken.
- [ ] `version` auf 0.5.0, `git push --atomic origin main v0.5.0`, Action abwarten, dann in Home Assistant aktualisieren.

## Später

- Platzhalter direkt mit Zutatenzeilen füllen (`get_recipe_details`; Nährwerte nur als Vergleich, Regel 2)
- Einkaufsliste wahlweise an Cookidoo statt an Bring (`add_ingredient_items_for_recipes`)
