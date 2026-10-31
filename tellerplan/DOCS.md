# Tellerplan

Kalorien zählen, Rezepte verwalten und die Woche planen – direkt in Home Assistant.

## Zugang

- **Oberfläche in Home Assistant:** über die Seitenleiste (Ingress), ohne eigenes Login.
- **Vollbild-App:** `http://<IP von Home Assistant>:8099/`, z. B. `http://192.168.178.20:8099/`. Die Anmeldung läuft über Home Assistant: Wer sich dort anmelden kann, kommt auch in Tellerplan. In den Einstellungen von Tellerplan lässt sich das Gerät wieder abmelden; das entzieht den Zugang auch in Home Assistant.
- **API:** ebenfalls Port 8099, aber unter `/api/…` und nur mit `Authorization: Bearer <api_token>`. Ohne gesetzten Token ist die API gesperrt.

### Vollbild-App auf dem iPhone

1. Port 8099 im Abschnitt „Netzwerk“ des Add-ons eintragen (Vorgabe 8099).
2. In Safari `http://<IP von Home Assistant>:8099/` öffnen und mit dem Home-Assistant-Benutzer anmelden.
3. Teilen → „Zum Home-Bildschirm“. Tellerplan startet dann im Vollbild mit eigenem Symbol.

Erreicht das iPhone Home Assistant unter einer anderen Adresse als Tellerplan (anderer Host oder Port), diese als `homeassistant_url` eintragen.

**IP-Adresse statt `homeassistant.local`:** Über `homeassistant.local` kann iOS nach der Anmeldung mit `NSURLErrorDomain` scheitern (vermutlich löst iOS den Namen per IPv6 auf, Port 8099 ist aber nur über IPv4 erreichbar). Zuverlässig ist die IP-Adresse, z. B. `http://192.168.178.20:8099/`. Damit das Symbol auf dem Home-Bildschirm dauerhaft funktioniert, dem Raspberry Pi im Router eine feste IPv4-Adresse geben (FRITZ!Box: „Diesem Netzwerkgerät immer die gleiche IPv4-Adresse zuweisen“).

## Optionen

| Option | Bedeutung |
| --- | --- |
| `daily_kcal_limit` | Tageslimit in kcal |
| `protein_goal_g`, `fat_goal_g`, `carbs_goal_g` | Makro-Ziele in Gramm pro Tag |
| `meal_names` | Namen der Mahlzeiten im Tagebuch |
| `plan_default_meal` | Vorausgewählte Mahlzeit, wenn ein geplantes Rezept eingetragen wird (muss in `meal_names` stehen) |
| `suggest_yesterday_meals` | Mahlzeiten, bei denen beim Eintragen das Rezept vom Vortag (gleiche Mahlzeit) oben steht und vorausgewählt ist, z. B. `Mittag`, `Snacks` |
| `frequency_window_days` | Beim Eintragen stehen Lebensmittel und Rezepte weiter oben, die du in so vielen zurückliegenden Tagen oft gegessen hast (gleiche Mahlzeit zählt doppelt); Vorgabe 90 |
| `recipe_categories` | Auswahl für die Kategorie eines Rezepts, z. B. Hauptgericht, Beilage, Snack |
| `meal_categories` | Vorfilter beim Eintragen: je Zeile eine Mahlzeit (`meal`) und eine Kategorie (`category`); mehrere Zeilen je Mahlzeit erlaubt. Mahlzeiten ohne Zeile zeigen alle Rezepte |
| `standard_units` | Gramm je Einheit für alle Lebensmittel ohne eigene Angabe (`unit`, `grams`), Vorgabe 1 EL = 15 g, 1 TL = 5 g; eine Einheit am Lebensmittel geht vor |
| `ranking_protein_weight` | Startwert des Reglers Eiweiß/Kalorien in der Rezeptliste (0–1) |
| `pantry_keywords` | Vorrat: Stichwörter für Artikel, die nicht auf die Einkaufsliste kommen; trifft Wörter, die damit enden („salz“ → „Meersalz“) |
| `bring_list_entity` | To-do-Liste der Bring-Integration für die Einkaufsliste, z. B. `todo.furth`; leer = nicht senden |
| `cookidoo_locale` | Sprache und Land von Cookidoo für den Abgleich mit „Meine Woche“, z. B. `de-DE` (cookidoo.de), `de-AT`, `de-CH`; Vorgabe `de-DE` |
| `homeassistant_url` | Adresse von Home Assistant aus Sicht des iPhones, z. B. `http://homeassistant.local:8123`; leer = gleicher Host wie Tellerplan, Port 8123 |
| `api_token` | Token für Kurzbefehle und Skripte |
| `database_path` | Pfad der SQLite-Datenbank (Standard `/data/app.db`, Teil der HA-Backups) |

Tageslimit, Makro-Ziele, Bring-Liste und Vorrat lassen sich auch in Tellerplan ändern: auf „Heute“ oben rechts das Zahnrad. Die Werte landen in denselben Optionen und erscheinen auch hier im Reiter „Konfiguration“.

Steht beim Start eine Migration an, sichert das Add-on die Datenbank vorher als `app.db.<Zeitstempel>.bak`; die letzten drei Sicherungen bleiben erhalten.

## Cookidoo

Einstellungen → Cookidoo → „Verbinden“ meldet Tellerplan bei Cookidoo an (OAuth). E-Mail und Passwort gehen nur einmal an Cookidoo und werden nicht gespeichert; Tellerplan behält nur die Anmeldung (Tokens) in `/data/cookidoo_token.json`, die sich selbst erneuert und Teil der HA-Backups ist. „Trennen“ löscht sie. Das Land richtet sich nach `cookidoo_locale`.

Cookidoo bietet keine offizielle Schnittstelle; Tellerplan nutzt die Bibliothek `cookidoo-api`, auf der auch die Cookidoo-Integration von Home Assistant aufbaut. Ändert Vorwerk etwas, kann der Abgleich zeitweise ausfallen; der Plan funktioniert dann weiter wie bisher.
