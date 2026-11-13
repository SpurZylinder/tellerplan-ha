# Version 0.6.0

Plan vom 2026-11-13. Rahmen und Regel für Befunde: [[Versionsplan]]. Aufbau wie bei [[Cookidoo-Sync]]: Jeder Schritt ist für sich lauffähig, mit Tests, und darf als **0.5.x** erscheinen. 0.6.0 wird erst gesetzt, wenn der Test auf dem Pi vollständig abgeschlossen ist.

**Reihenfolge:** Zuerst Teil A, die offenen Befunde. Danach Teil B, mehrere Benutzer. Teil A räumt die Stellen auf, die Teil B anfasst (Optionen, Tagebuch-Snapshot, Einstellseite), und sichert die Daten vor der großen Migration.

## Ziel

- Alle offenen Befunde sind behoben oder per Entscheidung mit Datum verschoben.
- Mehrere Personen im Haushalt nutzen Tellerplan über ihren eigenen Home-Assistant-Benutzer. **Dafür reicht ein Benutzer ohne Admin-Rechte in Home Assistant.** „Heute“ und die Ziele gelten je Benutzer. Lebensmittel, Rezepte, Plan und Einkaufsliste bleiben gemeinsam.
- Wer kein Admin ist, kann in Tellerplan nichts verstellen, was alle betrifft (Optionen, Cookidoo-Zugang, Bring-Liste, Datenpflege).

## Teil A: Befunde beheben

Beschreibung der Befunde in [[Architektur#Ausbaustufen und offene Punkte]]. Hier steht nur, wie sie behoben werden. Wo eine Entscheidung nötig ist, steht ein Vorschlag.

### A1: Datensicherheit (vor jeder weiteren Migration)

- [x] **K4 HA-Sicherung „hot“** (0.5.1)**:** `backup: cold` (entschieden 2026-11-13). Home Assistant hält das Add-on während der Sicherung kurz an, die Datenbank ist dann geschlossen und konsistent. Einfacher und sicherer als `backup_pre` mit Checkpoint, der Preis ist eine Pause von wenigen Sekunden. Pi-Test 2026-11-13: HA-Backup mit 0.5.1 enthält `app.db` ohne `-wal`/`-shm` (Datenbank war geschlossen), `options.json`, `cookidoo_token.json` und die drei Migrationssicherungen, keine `.tmp`-Reste. Offen: Wiederherstellen (Test auf dem Pi, Punkt 9). Test auf dem Pi: Sicherung anlegen, wiederherstellen, Daten vollständig.
- [x] **C-D Optionen nicht atomar** (0.5.1, gemeinsamer Helfer `files.write_text_atomic`, auch für die Cookidoo-Tokens)**:** `settings.save_options` (`settings.py:149-162`) schreibt atomar wie die Token-Datei in 0.4.15 (Nachbardatei, `fsync`, `os.replace`). Schlägt das Schreiben nach dem Supervisor-Aufruf fehl, kommt eine klare Meldung und die App liest die Optionen neu.
- [x] **K8 Zwei Schreiber** (0.5.1, `supervisor.get_own_options`; die Seite übergibt nur Felder, die anders sind als angezeigt)**:** Vor dem Speichern liest die Einstellseite die aktuellen Optionen beim Supervisor (`GET /addons/self/info`) und ändert nur die Felder, die auf der Seite geändert wurden. Eine Änderung in Home Assistant geht dann nicht mehr verloren. Mit Teil B wandern die Ziele ohnehin in die Datenbank.
- [x] **C-C Zwei Quellen für Optionen** (0.5.1, `tests/test_config_consistency.py`, prüft auch `dev/options.example.json`; PyYAML nur in `requirements-dev.txt`)**:** Ein Test vergleicht `settings.py` mit `options` und `schema` in `config.yaml`: gleiche Schlüssel, gleiche Vorgabewerte, gleiche Wertebereiche.

- [x] **K17 Einstellungen kommen nicht in Home Assistant an** – geschlossen 2026-11-13, kein Befund: Beim Pi-Test von 0.5.1 falsch beobachtet; Änderungen auf der Einstellseite landen im Reiter „Konfiguration“. Aus der Prüfung bleibt in 0.5.2: Nach dem Senden liest Tellerplan die Optionen beim Supervisor zurück und meldet einen Fehler, wenn sie nicht übernommen wurden.
- [x] **C-J INFO-Meldungen fehlen im Protokoll** (neu 2026-11-13, behoben 0.5.2): Die Migration beim Start las `alembic.ini` und setzte den Root-Logger auf WARNING; danach fehlten alle INFO-Meldungen der App, z. B. „Optionen gespeichert“. Jetzt richtet nur noch die Alembic-Kommandozeile ihr Logging selbst ein (`configure_logger` in `migrate.alembic_config`).

### A2: Alltag

- [x] **K13 Browser-Cache** (0.5.3): `url('static', …)` hängt `?v=` mit einem Hash des Dateiinhalts an (`web/templating.asset_version`). Abweichung vom Plan: Inhalts-Hash statt Version, weil `config.yaml` nicht im Image liegt und sich der Link so nur ändert, wenn sich die Datei ändert.
- [x] **K11 Zeiträume** (0.5.3): `modules/planner/service.PLAN_DAYS_AHEAD` und `plan_horizon(today)`; Plan, Einkaufsliste, Abgleich und „Verbindung prüfen“ reichen alle bis heute + 14. `build_shopping_list` bekommt Anfang und Ende statt einer Anzahl Tage. Grenztest in `test_shopping.py`.
- [x] **K10 Einheiten-Schreibweisen** (0.5.3): neues Modul `modules/foods/units.py` mit einer Schreibweise je Einheit, genutzt von Zeilenparser und Einkaufsliste. Die Einkaufsliste rechnet kg → g und l → ml, zeigt ab 1000 wieder kg/l und fasst eigene Einheiten („Zehe“/„zehe“) ohne Groß/klein zusammen.
- [x] **K9 Zutat ohne Einheit = Gramm** (geprüft 0.5.3): Der Zeilenparser setzt bei einer Menge immer eine Einheit („2 Eier“ → 2 Stück); Gramm ohne Einheit gilt nur noch im Tagebuch, wo man Gramm einträgt. Gefundene Lücke behoben: „gr“, „Stk“, „Pkg.“, „Esslöffel“ u. a. wurden nicht erkannt („500 gr Mehl“ → 500 Stück „gr Mehl“).
- [x] **C-I Kleinigkeiten** (0.5.3): `add_entry` lehnt 0 oder weniger Portionen ab; `web/pages/options.py` heißt jetzt `settings_page.py` wie die Route. `ShoppingItem.optional` geschlossen, kein Befund (2026-11-13): `shopping` darf nach Regel 7 auf `recipes` zugreifen.
- [x] **K24 Rezept fälschlich unvollständig („10/9 Zutaten“)** (neu 2026-11-13, behoben 0.5.15): Eine Grundzutat „ohne Nährwerte“ mit Standardprodukt (Pfeffer) zählte doppelt, als zugeordnet und als ohne Nährwerte. `summarize` zählt jetzt jede Pflichtzeile einmal (keine offene Frage laut `ingredient_issue`).
- [x] **K25 Offene Zutat am Rezept hervorheben** (Wunsch 2026-11-13, umgesetzt 0.5.15): Zeilen, die noch nicht in die Nährwerte eingehen, sind in der Zutatenliste farbig hinterlegt (kcal-Farbe), zusätzlich zum Hinweis an der Zeile.

### A3: Robustheit und Aufbau

- [x] **C-E Netzwerk im Fachmodul** (0.5.4): `modules/shopping` kennt den Supervisor nicht mehr. Die Seite reicht `add_item(name, description)` herein (`web/pages/shopping.todo_list_sender`), Fehler kommen als `SendError` aus dem Fachmodul.
- [x] **C-A Senden blockiert** (0.5.4): gelöst über das Senden im Hintergrund (A3b/K18) und 5 s je Artikel statt 10 s. Eine zuerst gebaute Gesamtfrist von 25 s wurde wieder entfernt: Sie hätte Teil-Sendungen erzeugt, die der nächste Klick doppelt schickt (K19).
- [x] **C-G Testlücken** (0.5.4/0.5.5): Datumsgrenzen um Mitternacht für Plan, Heute und Einkaufsliste (`tests/test_date_boundaries.py`); `pytest --cov` in der CI ohne Mindestwert, Stand 91 %; Test-Clients schließen ihre Datenbank-Engine. Echte Supervisor-Antworten: die aufgezeichnete Antwort von `todo.get_items` (`tests/data/bring_get_items.json`, 0.5.5).

- [x] **C-K Zeitstempel der Sicherung in Container-Zeit** (neu 2026-11-13, behoben 0.5.4): `db.backup_database` nutzte `datetime.now()` statt der zentralen Uhr; jetzt `clock.now()`.

### A3b: Einkaufsliste an Bring (neu 2026-11-13, Befunde aus dem Alltag)

- [x] **K18 Keine Statusmeldung nach „🛒 Einkaufsliste“** (0.5.4): Bestätigt am Pi (das Senden lief im Hintergrund zu Ende, die Rezepte galten danach als gesendet). Jetzt startet der Klick das Senden in einem eigenen Thread und zeigt sofort „Wird gesendet … n von m Artikel“; die Seite fragt alle 2 s nach (HTMX, `/plan/shopping/status`) und lädt am Ende mit dem Ergebnis neu.
- [x] **K19 Bring wird zugemüllt:** (a) behoben 0.5.4: Läuft ein Senden, startet ein weiterer Klick nichts Neues. (b) behoben 0.5.5: Vor dem Senden liest Tellerplan die offenen Einträge (`todo.get_items`); ein Artikel mit gleichem Namen (toleranter Vergleich wie beim Zuordnen, `alias_key`) wird per `todo.update_item` ergänzt (`merge_description`: Mengen addiert, Produkte zusammengeführt; fremde Angaben werden angehängt), neue per `todo.add_item` angelegt. Gesendet und abgehakt wird je Rezept; ist die Liste nicht lesbar, wird nichts gesendet.
- [x] **Einträge ohne Angaben bleiben unberührt** (Wunsch 2026-11-13, 0.5.6): Steht ein Artikel von Hand ohne Angaben in Bring („Oliven“), sind vielleicht andere gemeint; der Artikel aus dem Rezept kommt als eigener Eintrag dazu, weitere Rezepte ergänzen diesen. Ergänzt wird nur ein Eintrag mit Angaben.
- [x] **K22 Gesperrte Knöpfe sehen aktiv aus** (neu 2026-11-13, behoben 0.5.6): „An Bring senden“ war ohne neue Rezepte gesperrt, sah aber unverändert aus; `.btn:disabled` ist jetzt blass.
- [x] **K21 Ergänzen traf den falschen gleichnamigen Eintrag** (neu 2026-11-13, behoben 0.5.6): Ein eben angelegter Eintrag hat für Tellerplan noch keine `uid`; das Update über den Namen traf bei gleichnamigen Einträgen den ersten. Jetzt schlägt Tellerplan die `uid` vorher in der Liste nach (gleicher Name und genau die geschriebenen Angaben).
- [x] **K20 Produktname statt Grundzutat** (0.5.4): Artikel = Grundzutat, sonst Einkaufsname des Lebensmittels; REWE- und Open-Food-Facts-Produkte stehen in den Details („200 g · ja! Tomatenmark“). Die Vorratsprüfung sieht auch den Namen der Grundzutat.

**Vorschlag:**

1. **Name (K20):** Artikel = Grundzutat; ohne Grundzutat der Einkaufsname des Lebensmittels, sonst wie bisher. Ist ein Produkt zugeordnet (nicht BLS), steht es in den Details: „Tomatenmark“ – „200 g · ja! Tomatenmark“.
2. **Erweitern statt hinzufügen (K19b):** Vor dem Senden liest Tellerplan die offenen Einträge der Bring-Liste (`todo.get_items`). Gibt es den Artikel schon, ergänzt `todo.update_item` die Menge („300 g“ + „200 g“ → „500 g“); passt die vorhandene Angabe nicht ins Format (z. B. von Hand geändert), wird angehängt („2 Stück + 200 g“). Neue Artikel kommen per `todo.add_item`.
3. **Je Rezept senden und abhaken (K19a):** Die Rezepte gehen nacheinander raus, jedes gilt sofort nach seinen Artikeln als gesendet. Bricht etwas ab, wiederholt der nächste Lauf höchstens ein Rezept, nicht alle.
4. **Im Hintergrund mit Fortschritt (K18):** Der Klick startet das Senden und zeigt sofort „Wird gesendet …“; die Seite fragt alle zwei Sekunden den Stand ab (HTMX) und zeigt am Ende das Ergebnis. Ein zweiter Klick während des Sendens startet nichts Neues.
5. **Erkundung auf dem Pi zuerst:** Liefert `todo.get_items` über den Supervisor-Proxy die Einträge der Bring-Liste (REST mit `?return_response`)? Kann `todo.update_item` bei Bring die Spezifikation ändern? Antworten dabei als Testdaten aufzeichnen (Rest von C-G).

**Prüfung auf dem Pi (0.5.4, 2026-11-13):** „Bring-Liste prüfen“ zeigte `supported_features` 71 (Anlegen, Löschen, Ändern, Beschreibung) und die offenen Einträge mit `summary`, `uid`, `status`, `description`. Ein Auszug liegt als Testdaten in `tests/data/bring_get_items.json`. Fortschritt und Namen nach Grundzutat liefen; „Alles erneut senden“ legte erwartungsgemäß Duplikate an (K19b). Pi-Test 0.5.5: Ein weiteres Rezept ergänzte die vorhandenen Knoblauchzehen, Meldung „11 Artikel neu, 1 ergänzt“ (K19b bestätigt). Ein Produkt ohne Grundzutat („Cherry Romatomaten 250g“) heißt seit 0.5.5 ohne Packungsgröße; richtig wird es mit einer Grundzutat an der Rezeptzeile.

### A4: Sicherheit

- [x] **C-H Kein CSRF-Schutz** (0.5.7): `security.SameOriginMiddleware` auf beiden Ports. Schreibende Anfragen (POST, PUT, PATCH, DELETE) der Oberfläche brauchen einen `Origin` (sonst `Referer`), dessen Host zu `Host` oder `X-Forwarded-Host` passt; sonst 403 mit Eintrag im Protokoll (Herkunft und erwarteter Host). Die API (`/api/`) ist ausgenommen (Token, keine Cookies); ohne `Origin` und `Referer` (kein Browser) wird nicht geprüft. Auf dem Pi zu bestätigen: Über Ingress setzt Home Assistant nach unserer Kenntnis `X-Forwarded-Host`.
- [x] **`hassio_api` nötig?** (0.5.7): entfernt. Der Supervisor lässt `/addons/self/…` (u. a. `info`, `options`) für jedes Add-on zu; `hassio_api` öffnet nur die übrige Supervisor-API, die Tellerplan nicht nutzt. Auf dem Pi zu bestätigen; falls B1 (Benutzer prüfen) das Recht braucht, dort mit Begründung neu entscheiden.
- [x] **C-M Lücke in `opentelemetry-api` 1.45.1** (neu 2026-11-13, behoben 0.5.14): Die Abhängigkeitsprüfung der CI (`pip-audit`) meldete nach dem Release 0.5.13 CVE-2026-126360; die gepinnte Version in `constraints.txt` ist jetzt 1.45.2. Das Paket kommt über FastAPI mit, Tellerplan nutzt es nicht selbst.
- [ ] **K16 Jeder HA-Benutzer darf alles:** wird mit Teil B behoben (Rollen), steht hier nur zur Vollständigkeit.

**Pi-Test 0.5.7 (2026-11-13), bestanden:** Einstellungen speichern ohne `hassio_api` („Optionen an Home Assistant übergeben und bestätigt“, Wert im Reiter „Konfiguration“); Änderung in HA ohne Neustart bleibt beim Speichern in Tellerplan erhalten (K8); nach Neustart gelten die Werte aus HA; Bring sendet weiter (`homeassistant_api`); alle Formulare über Ingress gehen durch, keine Ablehnung durch den Herkunftsschutz (C-H). Statische Dateien kommen mit `?v=` und nach dem Neustart als `304 Not Modified` (K13). Offen: ein Formular in der Vollbild-App (Port 8099).

### A5: Datenmodell

- [x] **K15 Snapshot mit vier Nährwerten** (0.5.8): Migration 0017 ergänzt `diary_entry` um Ballaststoffe, Zucker, Salz. `Nutrients` rechnet sie mit; fehlt ein Wert am Lebensmittel, ist er unbekannt (`None`) und eine Summe damit auch, statt still 0 zu zählen. Alte Einträge bleiben leer. Angezeigt werden die drei Werte noch nicht.
- [x] **K6 Reste und mehrere Esser:** Entschieden 2026-11-13: Eine Erledigt-Logik über gegessene Portionen ist nicht nötig; der Plan muss Mahlzeiten nicht als gegessen markieren. Kein Befund mehr, sondern eine Komfort-Idee, die **zum Abschluss von 0.6.0** neu bewertet wird (siehe unten). Was bleibt, gehört zu B3: Das vorhandene „✓ eingetragen“ auf „Heute“ gilt je Benutzer.
- [x] **K7 Doku und Umsetzung** (0.5.8): Datenmodell und Systemübersicht in [[Architektur]] nachgezogen (`shopping`, sieben Nährwerte im Snapshot, `goal` und `weight` als geplant, `import_job` als Idee).

### A6: Plan (Befund und Wunsch vom 2026-11-13)

- [x] **K23 Plan springt nach dem Bearbeiten zum Tag** (0.5.8): Nach Verschieben, Löschen oder „Auf heute“ leitete die Seite auf `#day-…` weiter. Jetzt ohne Sprungziel; `plan.js` merkt sich beim Abschicken die Scrollposition (waagerecht und senkrecht, `sessionStorage`, 60 s) und stellt sie wieder her. Nach „+ Einplanen“ springt der Plan weiter zum neuen Tag.
- [x] **Datum wählen verschiebt sofort** (Wunsch, 0.5.8): Das Datumsfeld eines Planeintrags zeigt seinen eigenen Tag; ein anderer im Kalender gewählter Tag verschiebt sofort, der Knopf „Verschieben“ ist ausgeblendet (ohne JavaScript bleibt er). Wer das Datum tippt, verschiebt erst beim Verlassen des Felds.
- [ ] Test am iPhone: Verschieben über den Kalender, Ansicht bleibt an der Stelle (Spalten und Liste).

## Teil B: Mehrere Benutzer

### Ausgangslage

| | Ingress (Port 8000) | Vollbild-App (Port 8099) |
| --- | --- | --- |
| Wer kommt rein | Wer das Panel in Home Assistant sieht: heute nur Admins (`panel_admin` steht auf der Vorgabe `true`) | Jeder Home-Assistant-Benutzer nach der Anmeldung über OAuth |
| Wer ist es | Unbekannt; Home Assistant schickt den Benutzer aber in Kopfzeilen mit | Unbekannt; die Sitzung speichert nur den Refresh-Token |
| Was darf er | Alles | Alles, auch die Einstellseite (**K16**) |

### Sicherheitsmodell

1. **Home Assistant ist die einzige Anmeldung.** Tellerplan hat keine eigenen Passwörter, wie bisher.
2. **Familienmitglieder bekommen Benutzer ohne Admin-Rechte in Home Assistant**, am besten mit „Nur im lokalen Netz anmelden“. Ein Admin-Konto auf dem Handy der Familie ist nicht mehr nötig. Das ist der größte Sicherheitsgewinn: Ein verlorenes Handy oder ein geteiltes Passwort öffnet dann nicht mehr ganz Home Assistant.
3. ~~**Das Add-on öffnet das Panel für Nicht-Admins:** `panel_admin: false`~~ – entfällt (2026-11-13): Nicht-Admins nutzen die Vollbild-App, das Panel bleibt nur für Admins.
4. **Tellerplan prüft selbst, wer was darf.** Ohne eigene Freigabe hätte jeder HA-Benutzer Zugriff. Darum:
   - Option `allowed_users` (Liste von HA-Benutzernamen). Leer heißt: alle HA-Benutzer. Wer nicht auf der Liste steht, bekommt eine Seite „Kein Zugriff“.
   - Zwei Rollen, abgeleitet aus Home Assistant: **Verwalter** = Admin in Home Assistant, **Benutzer** = alle anderen. Keine eigene Rollenpflege in Tellerplan.
5. **Kopfzeilen nur vom Ingress-Proxy glauben.** Die Benutzer-Kopfzeilen von Home Assistant gelten nur auf dem Ingress-Port, und dort lässt `security.py` ohnehin nur `172.30.32.2` herein. Auf Port 8099 werden sie entfernt, bevor die App sie sieht. Sonst könnte sich jeder im Heimnetz per Kopfzeile als Admin ausgeben.

### Wer darf was (entschieden 2026-11-13)

| Bereich | Benutzer | Verwalter |
| --- | --- | --- |
| Heute: eigenes Tagebuch eintragen, ändern, löschen | ✅ | ✅ |
| Eigene Ziele (kcal, Eiweiß, Fett, KH) | ✅ | ✅ |
| Tagebuch anderer ansehen | ❌ | ❌ (streng getrennt, entschieden 2026-11-13) |
| Plan: einplanen, verschieben, entfernen | ✅ | ✅ |
| Rezepte anlegen, bearbeiten, zuordnen | ✅ | ✅ |
| Rezepte und Lebensmittel löschen | ❌ | ✅ |
| Einkaufsliste an Bring senden | ✅ | ✅ |
| Abgleich mit Cookidoo (gemeinsamer Zugang) | ✅ | ✅ |
| Cookidoo verbinden und trennen | ❌ | ✅ |
| Optionen: Mahlzeiten, Kategorien, Vorrat, Bring-Liste, Vorgabe-Ziele | ❌ | ✅ |
| Importe (Rezepte, Lebensmittel, Platzhalter füllen) | ❌ | ✅ |
| Benutzer freigeben, alte Einträge zuordnen | ❌ | ✅ |

Die Seiten zeigen nur, was der Benutzer darf. Jede Route prüft es zusätzlich auf dem Server, nicht nur über ausgeblendete Knöpfe.

### Benutzer erkennen

- **Ingress:** Home Assistant setzt `X-Remote-User-Id`, `X-Remote-User-Name` und `X-Remote-User-Display-Name`. Ob jemand Admin ist, steht nicht darin. Das muss Tellerplan bei Home Assistant nachfragen (siehe B1).
- **Vollbild-App:** Bei der Anmeldung tauscht Tellerplan den Code ohnehin gegen Tokens. Mit dem Access-Token fragt es Home Assistant über die Websocket-API `auth/current_user` nach Benutzer-ID, Name und `is_admin`. Die Sitzung speichert die Benutzer-ID. Die Rolle wird bei jeder Prüfung der Sitzung (alle 30 Minuten) erneuert. Wird jemandem in HA die Admin-Rolle entzogen, gilt das spätestens nach 30 Minuten auch in Tellerplan.
- **Lokal ohne Supervisor:** ein fester Entwicklungsbenutzer aus `dev/options.json`, damit Tests und lokale Arbeit gehen.

### Schritte

#### B1: Erkundung auf dem Pi (0.5.x, ändert nichts)

Wie Schritt 1 bei [[Cookidoo-Sync]]: Erst messen, dann bauen. Einstellungen bekommt einen Abschnitt „Benutzer prüfen“, der nur anzeigt (0.5.9, Modul `ha_users.py`). Er probiert vier Wege und zeigt je Ergebnis und Rohantwort:

1. Kopfzeilen `X-Remote-User-*` der aktuellen Anfrage (über Ingress).
2. Supervisor-API `GET /auth/list`.
3. Websocket von Home Assistant `config/auth/list` mit `SUPERVISOR_TOKEN` über den Supervisor-Proxy (`ws://supervisor/core/websocket`); Admins an der Gruppe `system-admin`.
4. Vollbild-App: Zugang aus dem Refresh-Token der Sitzung, dann Websocket `auth/current_user` (`id`, `name`, `is_admin`).

`panel_admin` bleibt in 0.5.9 auf der Vorgabe (`true`): Mit `false` sähen Nicht-Admins Tellerplan schon jetzt mit allen Rechten (K16). Die Punkte zu Nicht-Admins unten werden darum in B2 geprüft, zusammen mit den Rollen.

**Ergebnis auf dem Pi (0.5.9, 2026-11-13):**

- [x] Kopfzeilen über Ingress: ✓ `X-Remote-User-Id` (HA-Benutzer-ID), `-Name` (Benutzername), `-Display-Name`.
- [x] Supervisor-API `GET /auth/list`: ✗ 403 – wird nicht gebraucht, darum kein zusätzliches Recht.
- [x] Websocket `config/auth/list` mit `SUPERVISOR_TOKEN` über `ws://supervisor/core/websocket`: ✓ alle Benutzer mit `id`, `username`, `name`, `is_owner`, `is_active`, `local_only`, `system_generated`, `group_ids`. Admin = Gruppe `system-admin`. Reicht mit dem vorhandenen `homeassistant_api`.
- [x] Vollbild-App `auth/current_user` mit dem Zugang aus der Sitzung: ✓ `id`, `name`, `is_owner`, `is_admin`.
- [x] Nicht-Admin und das Panel mit `panel_admin: false` – entfällt (2026-11-13), Nicht-Admins nutzen die Vollbild-App.
- Befund dabei: Es gibt bereits einen Benutzer ohne Admin-Rechte („Fabian“, `system-users`). Er könnte sich heute in der Vollbild-App anmelden und hätte alle Rechte (K16, nicht nur theoretisch). Sofortmaßnahme als erster Teil von B2.

**Entscheidung für B2:** Wer es ist, kommt über Ingress aus den Kopfzeilen, in der Vollbild-App aus `auth/current_user` bei der Anmeldung (ID in der Sitzung). Ob jemand Admin und aktiv ist, kommt für beide aus `config/auth/list` (kurz zwischengespeichert). Systembenutzer (`system_generated`) kommen nie herein.

#### B2a: Sofortmaßnahme K16 (0.5.10)

- [x] Vollbild-App vorerst nur für Admins: Nach dem Einlösen des Codes fragt Tellerplan `auth/current_user` ab (`ha_users.session_user`). Wer kein Admin ist, bekommt „Kein Zugriff“ (403), und der eben erteilte Zugang wird in Home Assistant wieder entzogen. Ist der Benutzer nicht abfragbar, gibt es keine Sitzung (502).
- [x] Die Prüfung der Sitzung alle 30 Minuten fragt auch die Rolle ab: kein Admin mehr → Sitzung beendet. Home Assistant nicht erreichbar → bestehende Sitzung gilt weiter (wie bisher). Bestehende Sitzungen werden damit spätestens 30 Minuten nach dem Update geprüft.
- [x] `ha_auth.check_refresh_token` entfällt; `access_token` prüft den Zugang mit.
- [x] Test auf dem Pi (2026-11-13): Admin meldet sich in der Vollbild-App an wie bisher; ein Benutzer ohne Admin-Rechte bekommt die Seite „Kein Zugriff“ von Tellerplan (ohne Tab-Leiste, mit „Mit Home Assistant anmelden“ für ein anderes Konto).

#### B2b: Benutzer und Rollen (0.5.11, Teil 1)

Umgesetzt in 0.5.11 (das Panel bleibt noch nur für Admins sichtbar):

- [x] Modul `modules/users` mit Tabelle `app_user` (HA-Benutzer-ID, Name, zuerst/zuletzt gesehen), Migration 0018; Regel 7: `users` ← `diary`.
- [x] `web/access.py`: `require_user` ermittelt je Anfrage den Benutzer (`CurrentUser`): über Ingress aus `X-Remote-User-*`, in der Vollbild-App aus der Sitzung (`web_session.user_id`, Name, Admin-Recht; Migration 0018; ältere Sitzungen melden neu an). Im Add-on prüft er das Konto in der Benutzerliste von Home Assistant (`ha_users.directory`, `config/auth/list`, 60 s zwischengespeichert, bei Ausfall bis 1 h der letzte Stand): unbekannt, deaktiviert oder Systemkonto → „Kein Zugriff“; sonst Rolle aus der Gruppe `system-admin`. Lokal ohne Supervisor: ein lokaler Verwalter.
- [x] Option `allowed_users` (HA-Benutzernamen; leer = alle echten Benutzer).
- [x] `require_admin` an allen Verwalter-Seiten: Optionen speichern, Cookidoo verbinden/prüfen/trennen, „Benutzer prüfen“, „Bring-Liste prüfen“, alle Importe, Rezepte und Lebensmittel löschen, Grundzutaten zusammenführen (Vorschlag, weil unumkehrbar).
- [x] Oberfläche: Benutzer sehen die Tagesziele nur lesend, keine Cookidoo-Verbindung, keine Importe, keine Lösch- und Zusammenführen-Knöpfe; „Angemeldet als … · Verwalter/Benutzer“ in den Einstellungen. „Kein Zugriff“ als eigene Seite ohne Tab-Leiste.
- [x] Die Vollbild-App lässt jetzt auch Nicht-Admins herein, mit den Rechten eines Benutzers (löst die Sperre aus B2a ab).
- [x] `X-Remote-User-*` werden auf Port 8099 entfernt (`security._drop_remote_user_headers`).
- [x] Tests: `tests/test_roles.py` (Verwalter-Seiten, Freigabe, Systemkonten, Ausfall von Home Assistant, Zwischenspeicher).
- [x] **C-L Tests erreichten das echte Home Assistant** (neu 2026-11-13, behoben 0.5.11): Die Tests der Vollbild-App nutzten `homeassistant.local` als Adresse; ein nicht ersetzter Aufruf ging so an das echte Home Assistant im Heimnetz, das sechs fehlgeschlagene Anmeldungen protokollierte (Python-urllib, `/auth/token`, mit erfundenen Tokens, harmlos). Jetzt sperrt `tests/conftest.py` alle Netzwerkzugänge der App (`no_network`), und die Tests nutzen die reservierte Endung `.test`.

**Pi-Test 0.5.11 (2026-11-13):** Anmeldung als Admin und als Benutzer (Fabian) in der Vollbild-App funktioniert; Fabian kann „Heute“ bearbeiten und den Plan sehen, aber keine Rezepte löschen. Erwartet noch gemeinsam: Tagebucheinträge erscheinen bei beiden Benutzern (B3). Als Nächstes B3 (Tagebuch je Benutzer), weil Fabian schon einträgt; `panel_admin: false` entfällt.

#### B2b: Teil 2 – entfällt (Entscheidung 2026-11-13)

`panel_admin` bleibt auf der Vorgabe (`true`): Das Panel in Home Assistant ist nur für Admins; alle anderen Benutzer nutzen die Vollbild-App (`http://<IP>:8099/`), in der die Rollen gelten. Das ist auch die engere Lösung: Nicht-Admins brauchen keinen Zugang zur Oberfläche von Home Assistant.

Ursprünglicher Plan für B2b:

- [ ] Modul `users` (neu, unterhalb von `diary` in der Abhängigkeitsrichtung; Regel 7 um `users` ergänzen): Tabelle `app_user` (HA-Benutzer-ID, Name, zuletzt gesehen), `CurrentUser(id, name, is_admin)`.
- [ ] `web/access.py` ermittelt den Benutzer je Anfrage: Ingress aus den Kopfzeilen, Vollbild-App aus der Sitzung (`web_session.user_id`, Migration). Die Rolle wird kurz zwischengespeichert, damit nicht jede Anfrage bei Home Assistant nachfragt.
- [ ] `security.py` entfernt `X-Remote-User-*` auf Port 8099.
- [ ] Option `allowed_users`, Seite „Kein Zugriff“.
- [ ] Abhängigkeiten `require_admin` und `require_user` für die Routen nach der Tabelle oben. Die Oberfläche blendet aus, was nicht erlaubt ist.
- [x] ~~`panel_admin: false` in `config.yaml`~~ – entfällt (2026-11-13).
- [ ] Tests: jede Route mit Benutzer, Verwalter, nicht freigegebenem Benutzer und gefälschten Kopfzeilen auf Port 8099.
- [ ] Schließt **K16**.

#### B3: Tagebuch je Benutzer (0.5.12)

- [x] Migration 0019: `diary_entry.user_id` (HA-Benutzer-ID, Index, bewusst ohne Fremdschlüssel). Bisherige Einträge bleiben leer; Einstellungen → „Bisherige Tagebucheinträge“ (nur Verwalter, nur solange es welche gibt) gibt sie einmal einem bekannten Benutzer. Bis dahin sehen sie nur Verwalter. Umgesetzt in 0.5.12.
- [x] „Heute“, Verlauf, „Rezept von gestern“, Häufigkeit beim Eintragen, zuletzt eingetragene Menge und „aus dem Plan übernehmen“ lesen nur Einträge des aktuellen Benutzers (`diary.service.Viewer`, Pflichtangabe jeder Leseabfrage). Fremde Einträge lassen sich weder ändern noch löschen (404).
- [x] „✓ eingetragen“ auf „Heute“ zeigt nur, ob *der aktuelle Benutzer* den Planeintrag übernommen hat, nicht ein anderer.
- [x] Tests: `tests/test_diary_users.py` (zwei Benutzer über Ingress, fremde Einträge, Plan gemeinsam, Zuordnung alter Einträge).
- [x] Test auf dem Pi (0.5.12): Admin und Fabian tragen ein, keiner sieht den anderen; alte Einträge in den Einstellungen zugeordnet (bestätigt 2026-11-13).

#### B4: Ziele je Benutzer (0.5.13)

- [x] Tabelle `goal` (Benutzer, gültig ab, kcal, Eiweiß, Fett, KH; Migration 0020, eindeutig je Benutzer und Tag). Für einen Tag gilt das Ziel mit dem letzten „gültig ab“ bis zu diesem Tag (`modules.users.goals.goals_for`). Alte Tage laufen damit gegen das damalige Ziel.
- [x] Ohne eigenes Ziel gelten die Vorgabewerte aus den Optionen (entschieden 2026-11-13). Erst wenn der Benutzer speichert, entsteht ein eigener Eintrag in `goal`, gültig ab heute; eine zweite Änderung am selben Tag ersetzt die erste.
- [x] Regel 6 angepasst (CLAUDE.md und [[Architektur]]): Die Optionen liefern nur noch die Vorgabeziele, die eigenen Ziele stehen in der Datenbank.
- [x] Die Einstellseite trennt „Meine Tagesziele“ (alle) und „Optionen“ mit Vorgabezielen und Einkaufsliste (nur Verwalter).
- [x] Tests: `tests/test_goals.py` (Vorgabe, gültig ab, gleicher Tag ersetzt, alte Tage behalten ihr Ziel, zwei Benutzer, Eingabefehler).
- [ ] Test auf dem Pi (0.5.13): Fabian setzt eigene Ziele; Admin behält die Vorgabe; der Vortag zeigt weiter die alten Ziele.

#### B5: API und Doku (0.5.x)

- [ ] API auf Port 8099: bleibt in 0.6.0 beim einen `api_token` aus den Optionen. Sie liest heute nur (`GET /api/v1/recipes`, `/api/v1/health`) und kennt keine Benutzer. Ein Token je Benutzer wird erst nötig, wenn die API ins Tagebuch schreibt, also mit 0.8.0 (Apple Health); die Frage ist dorthin verschoben (2026-11-13).
- [x] `DOCS.md`: Benutzer anlegen (ohne Admin, „Nur lokal“), `allowed_users`, Rollen, Vollbild-App für Nicht-Admins (erledigt in 0.5.11).
- [ ] [[Architektur]]: Datenmodell, Zugriff je Port, Regel 6 und 7.

### Test auf dem Pi

1. [x] Nicht-Admin in HA anlegen (nur lokal). Er öffnet Tellerplan als Vollbild-App (0.5.11, Fabian). Über Ingress nicht nötig (Panel nur für Admins).
2. [ ] Er trägt auf „Heute“ ein und setzt eigene Ziele. Der Admin sieht davon nichts auf seinem „Heute“.
3. [ ] Er sieht weder Optionen noch Cookidoo-Verbinden noch Importe. Direkter Aufruf der Adressen ergibt „Kein Zugriff“.
4. [ ] Plan, Rezepte, Einkaufsliste und Cookidoo-Abgleich funktionieren für ihn.
5. [ ] Admin ordnet die bisherigen Einträge sich zu. Alte Tage zeigen die alten Werte.
6. [ ] Beide planen dasselbe Rezept; einer trägt es ein. Beim anderen steht es auf „Heute“ weiter zum Eintragen bereit.
7. [ ] Nicht freigegebener HA-Benutzer (wenn `allowed_users` gesetzt ist) bekommt „Kein Zugriff“.
8. [ ] Admin-Rolle in HA entziehen: Nach spätestens 30 Minuten ist die Einstellseite zu.
9. [ ] Sicherung über HA mit `backup: cold`, wiederherstellen, alles da (K4).

Erst wenn alle Punkte erledigt sind: Doku und Release 0.6.0.

## Entscheidungen (2026-11-13)

1. K4: `backup: cold`.
2. C-G: `pytest-cov` ohne Mindestwert.
3. K6: keine Erledigt-Logik über Portionen; als Komfort-Idee zum Abschluss von 0.6.0 neu bewerten.
4. Rollen: Tabelle „Wer darf was“ wie oben.
5. Tagebuch: streng getrennt, auch für Verwalter.
6. Ziele: Ohne eigene Änderung gelten die Vorgabewerte aus den Optionen.
7. API: in 0.6.0 weiter der eine `api_token` (nur lesend); Token je Benutzer mit 0.8.0.

## Zum Abschluss von 0.6.0 bewerten

- Planeinträge als gegessen markieren bzw. Reste über Portionen (Meal-Prep), früher K6. Vor dem Release 0.6.0 entscheiden: umsetzen, als Idee in den [[Versionsplan]] („Nicht eingeplant“) oder verwerfen.
