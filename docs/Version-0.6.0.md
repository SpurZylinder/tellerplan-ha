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

### A3: Robustheit und Aufbau

- [x] **C-E Netzwerk im Fachmodul** (0.5.4): `modules/shopping` kennt den Supervisor nicht mehr. Die Seite reicht `add_item(name, description)` herein (`web/pages/shopping.todo_list_sender`), Fehler kommen als `SendError` aus dem Fachmodul.
- [x] **C-A Senden blockiert** (0.5.4): gelöst über das Senden im Hintergrund (A3b/K18) und 5 s je Artikel statt 10 s. Eine zuerst gebaute Gesamtfrist von 25 s wurde wieder entfernt: Sie hätte Teil-Sendungen erzeugt, die der nächste Klick doppelt schickt (K19).
- [ ] **C-G Testlücken** (teilweise 0.5.4): Datumsgrenzen um Mitternacht für Plan, Heute und Einkaufsliste (`tests/test_date_boundaries.py`); `pytest --cov` in der CI ohne Mindestwert, Stand 91 %; Test-Clients schließen ihre Datenbank-Engine (vorher über 50 ResourceWarnings). Offen: echte Supervisor-Antworten als Testdaten – Vorschlag: in B1 aufzeichnen, dort wird die Supervisor-API ohnehin auf dem Pi abgefragt.

- [x] **C-K Zeitstempel der Sicherung in Container-Zeit** (neu 2026-11-13, behoben 0.5.4): `db.backup_database` nutzte `datetime.now()` statt der zentralen Uhr; jetzt `clock.now()`.

### A3b: Einkaufsliste an Bring (neu 2026-11-13, Befunde aus dem Alltag)

- [x] **K18 Keine Statusmeldung nach „🛒 Einkaufsliste“** (0.5.4): Bestätigt am Pi (das Senden lief im Hintergrund zu Ende, die Rezepte galten danach als gesendet). Jetzt startet der Klick das Senden in einem eigenen Thread und zeigt sofort „Wird gesendet … n von m Artikel“; die Seite fragt alle 2 s nach (HTMX, `/plan/shopping/status`) und lädt am Ende mit dem Ergebnis neu.
- [ ] **K19 Bring wird zugemüllt:** (a) behoben 0.5.4: Läuft ein Senden, startet ein weiterer Klick nichts Neues. (b) offen, 0.5.5: vorhandene Einträge in Bring erweitern statt neu anlegen (Vorschlag Punkt 2, nach der Prüfung auf dem Pi). Je Rezept senden und abhaken (Punkt 3) kommt erst mit (b), sonst gingen gleiche Artikel aus mehreren Rezepten einzeln und damit doppelt an Bring.
- [x] **K20 Produktname statt Grundzutat** (0.5.4): Artikel = Grundzutat, sonst Einkaufsname des Lebensmittels; REWE- und Open-Food-Facts-Produkte stehen in den Details („200 g · ja! Tomatenmark“). Die Vorratsprüfung sieht auch den Namen der Grundzutat.

**Vorschlag:**

1. **Name (K20):** Artikel = Grundzutat; ohne Grundzutat der Einkaufsname des Lebensmittels, sonst wie bisher. Ist ein Produkt zugeordnet (nicht BLS), steht es in den Details: „Tomatenmark“ – „200 g · ja! Tomatenmark“.
2. **Erweitern statt hinzufügen (K19b):** Vor dem Senden liest Tellerplan die offenen Einträge der Bring-Liste (`todo.get_items`). Gibt es den Artikel schon, ergänzt `todo.update_item` die Menge („300 g“ + „200 g“ → „500 g“); passt die vorhandene Angabe nicht ins Format (z. B. von Hand geändert), wird angehängt („2 Stück + 200 g“). Neue Artikel kommen per `todo.add_item`.
3. **Je Rezept senden und abhaken (K19a):** Die Rezepte gehen nacheinander raus, jedes gilt sofort nach seinen Artikeln als gesendet. Bricht etwas ab, wiederholt der nächste Lauf höchstens ein Rezept, nicht alle.
4. **Im Hintergrund mit Fortschritt (K18):** Der Klick startet das Senden und zeigt sofort „Wird gesendet …“; die Seite fragt alle zwei Sekunden den Stand ab (HTMX) und zeigt am Ende das Ergebnis. Ein zweiter Klick während des Sendens startet nichts Neues.
5. **Erkundung auf dem Pi zuerst:** Liefert `todo.get_items` über den Supervisor-Proxy die Einträge der Bring-Liste (REST mit `?return_response`)? Kann `todo.update_item` bei Bring die Spezifikation ändern? Antworten dabei als Testdaten aufzeichnen (Rest von C-G).

**Prüfung auf dem Pi (0.5.4):** Einkaufsliste → „Bring-Liste prüfen“ liest nur: `supported_features` der Liste und die offenen Einträge über `todo.get_items` (REST mit `?return_response`). Ergebnis und Rohantwort hier eintragen; sie werden die Testdaten für K19b (Rest von C-G).

### A4: Sicherheit

- [ ] **C-H Kein CSRF-Schutz:** Middleware für alle POST-Anfragen auf beiden Ports: Der Kopf `Origin` (ersatzweise `Referer`) muss zum eigenen Host passen, sonst 403. Das braucht keine Tokens in den Formularen und deckt HTMX mit ab. Das Sitzungs-Cookie der Vollbild-App hat schon `SameSite=Lax` (`web/pages/login.py:66`).
- [ ] **`hassio_api` nötig?** Offener Punkt aus der Architektur: Auf dem Pi prüfen, ob `/addons/self/options` auch ohne `hassio_api: true` geht. Wenn ja, das Recht entfernen. Weniger Rechte bedeutet weniger Risiko.
- [ ] **K16 Jeder HA-Benutzer darf alles:** wird mit Teil B behoben (Rollen), steht hier nur zur Vollständigkeit.

### A5: Datenmodell

- [ ] **K15 Snapshot mit vier Nährwerten:** Migration: `diary_entry` bekommt Ballaststoffe, Zucker und Salz. Neue Einträge speichern alle sieben Werte. Alte Einträge bleiben leer und zeigen „–“. Wird vor B3 erledigt, damit die Tabelle nur einmal umgebaut wird.
- [x] **K6 Reste und mehrere Esser:** Entschieden 2026-11-13: Eine Erledigt-Logik über gegessene Portionen ist nicht nötig; der Plan muss Mahlzeiten nicht als gegessen markieren. Kein Befund mehr, sondern eine Komfort-Idee, die **zum Abschluss von 0.6.0** neu bewertet wird (siehe unten). Was bleibt, gehört zu B3: Das vorhandene „✓ eingetragen“ auf „Heute“ gilt je Benutzer.
- [ ] **K7 Doku und Umsetzung:** Datenmodell in [[Architektur]] nachziehen: `ingredient_alias` gibt es, `goal` kommt mit B4, `weight` mit 0.8.0, `import_job` streichen oder als Idee markieren, `shopping` in die Systemübersicht.

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
3. **Das Add-on öffnet das Panel für Nicht-Admins:** `panel_admin: false` in `config.yaml`. Ohne das sieht ein Nicht-Admin Tellerplan gar nicht.
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

Wie Schritt 1 bei [[Cookidoo-Sync]]: Erst messen, dann bauen. Einstellungen bekommt einen Abschnitt „Benutzer prüfen“, der nur anzeigt.

- [ ] Kommen die Kopfzeilen `X-Remote-User-*` über Ingress an, für Admin und Nicht-Admin? (Für den Nicht-Admin vorher `panel_admin: false` setzen.)
- [ ] Sieht und öffnet ein Nicht-Admin das Panel mit `panel_admin: false`? Geht Ingress für ihn ohne Fehler?
- [ ] Wie erfährt Tellerplan über Ingress, ob jemand Admin ist? Kandidaten, zu prüfen in dieser Reihenfolge: Benutzerliste der Supervisor-API, Websocket `config/auth/list` über den Supervisor-Proxy mit `SUPERVISOR_TOKEN`. Welche Rechte (`hassio_role`, `homeassistant_api`) braucht das?
- [ ] Liefert `auth/current_user` mit dem Access-Token der Vollbild-App `id`, `name` und `is_admin`?
- [ ] Ergebnisse hier eintragen und danach das Rollenmodell bestätigen oder anpassen.

#### B2: Benutzer und Rollen (0.5.x)

- [ ] Modul `users` (neu, unterhalb von `diary` in der Abhängigkeitsrichtung; Regel 7 um `users` ergänzen): Tabelle `app_user` (HA-Benutzer-ID, Name, zuletzt gesehen), `CurrentUser(id, name, is_admin)`.
- [ ] `web/access.py` ermittelt den Benutzer je Anfrage: Ingress aus den Kopfzeilen, Vollbild-App aus der Sitzung (`web_session.user_id`, Migration). Die Rolle wird kurz zwischengespeichert, damit nicht jede Anfrage bei Home Assistant nachfragt.
- [ ] `security.py` entfernt `X-Remote-User-*` auf Port 8099.
- [ ] Option `allowed_users`, Seite „Kein Zugriff“.
- [ ] Abhängigkeiten `require_admin` und `require_user` für die Routen nach der Tabelle oben. Die Oberfläche blendet aus, was nicht erlaubt ist.
- [ ] `panel_admin: false` in `config.yaml`, mit Hinweis in `DOCS.md`.
- [ ] Tests: jede Route mit Benutzer, Verwalter, nicht freigegebenem Benutzer und gefälschten Kopfzeilen auf Port 8099.
- [ ] Schließt **K16**.

#### B3: Tagebuch je Benutzer (0.5.x)

- [ ] Migration: `diary_entry.user_id`. Bisherige Einträge haben noch keinen Besitzer. Die Einstellseite (nur Verwalter) zeigt einmalig „Bisherige Einträge gehören: [Benutzer]“. Bis dahin sieht sie nur der Verwalter. Nichts wird automatisch zugeordnet.
- [ ] „Heute“, Verlauf, „Rezept von gestern“, Vorfilter und „aus dem Plan übernehmen“ lesen nur Einträge des aktuellen Benutzers.
- [ ] „✓ eingetragen“ auf „Heute“ zeigt nur, ob *der aktuelle Benutzer* den Planeintrag übernommen hat, nicht ein anderer.
- [ ] Tests: zwei Benutzer am selben Tag, keiner sieht den anderen.

#### B4: Ziele je Benutzer (0.5.x)

- [ ] Tabelle `goal` (Benutzer, gültig ab, kcal, Eiweiß, Fett, KH). Für einen Tag gilt das Ziel mit dem letzten „gültig ab“ bis zu diesem Tag. Alte Tage laufen damit gegen das damalige Ziel.
- [ ] Ohne eigenes Ziel gelten die Vorgabewerte aus den Optionen (entschieden 2026-11-13). Erst wenn der Benutzer etwas ändert, entsteht ein eigener Eintrag in `goal`.
- [ ] Regel 6 anpassen (CLAUDE.md und [[Architektur]]): Die Optionen liefern nur noch die Vorgabeziele. Die eigenen Ziele stehen in der Datenbank. Gepflegt werden sie auf der Einstellseite, jeder Benutzer seine eigenen.
- [ ] Die Einstellseite trennt „Meine Ziele“ (alle) und „Optionen“ (nur Verwalter).
- [ ] Tests: Zieländerung wirkt ab dem Tag, alte Tage bleiben.

#### B5: API und Doku (0.5.x)

- [ ] API auf Port 8099: bleibt in 0.6.0 beim einen `api_token` aus den Optionen. Sie liest heute nur (`GET /api/v1/recipes`, `/api/v1/health`) und kennt keine Benutzer. Ein Token je Benutzer wird erst nötig, wenn die API ins Tagebuch schreibt, also mit 0.8.0 (Apple Health); die Frage ist dorthin verschoben (2026-11-13).
- [ ] `DOCS.md`: Benutzer anlegen (ohne Admin, „Nur lokal“), `panel_admin`, `allowed_users`, Rollen.
- [ ] [[Architektur]]: Datenmodell, Zugriff je Port, Regel 6 und 7.

### Test auf dem Pi

1. [ ] Nicht-Admin in HA anlegen (nur lokal). Er sieht das Panel und öffnet Tellerplan über Ingress und als Vollbild-App.
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
