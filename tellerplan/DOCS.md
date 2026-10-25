# Tellerplan

Kalorien zählen, Rezepte verwalten und die Woche planen – direkt in Home Assistant.

## Zugang

- **Oberfläche in Home Assistant:** über die Seitenleiste (Ingress), ohne eigenes Login.
- **Vollbild-App:** `http://<home-assistant>:8099/`, z. B. `http://homeassistant.local:8099/`. Die Anmeldung läuft über Home Assistant: Wer sich dort anmelden kann, kommt auch in Tellerplan. In den Einstellungen von Tellerplan lässt sich das Gerät wieder abmelden; das entzieht den Zugang auch in Home Assistant.
- **API:** ebenfalls Port 8099, aber unter `/api/…` und nur mit `Authorization: Bearer <api_token>`. Ohne gesetzten Token ist die API gesperrt.

### Vollbild-App auf dem iPhone

1. Port 8099 im Abschnitt „Netzwerk“ des Add-ons eintragen (Vorgabe 8099).
2. In Safari `http://homeassistant.local:8099/` öffnen und mit dem Home-Assistant-Benutzer anmelden.
3. Teilen → „Zum Home-Bildschirm“. Tellerplan startet dann im Vollbild mit eigenem Symbol.

Erreicht das iPhone Home Assistant unter einer anderen Adresse als Tellerplan (anderer Host oder Port), diese als `homeassistant_url` eintragen.

## Optionen

| Option | Bedeutung |
| --- | --- |
| `daily_kcal_limit` | Tageslimit in kcal |
| `protein_goal_g`, `fat_goal_g`, `carbs_goal_g` | Makro-Ziele in Gramm pro Tag |
| `meal_names` | Namen der Mahlzeiten im Tagebuch |
| `plan_default_meal` | Vorausgewählte Mahlzeit, wenn ein geplantes Rezept eingetragen wird (muss in `meal_names` stehen) |
| `ranking_protein_weight` | Startwert des Reglers Eiweiß/Kalorien in der Rezeptliste (0–1) |
| `pantry_keywords` | Vorrat: Stichwörter für Artikel, die nicht auf die Einkaufsliste kommen; trifft Wörter, die damit enden („salz“ → „Meersalz“) |
| `bring_list_entity` | To-do-Liste der Bring-Integration für die Einkaufsliste, z. B. `todo.furth`; leer = nicht senden |
| `homeassistant_url` | Adresse von Home Assistant aus Sicht des iPhones, z. B. `http://homeassistant.local:8123`; leer = gleicher Host wie Tellerplan, Port 8123 |
| `api_token` | Token für Kurzbefehle und Skripte |
| `database_path` | Pfad der SQLite-Datenbank (Standard `/data/app.db`, Teil der HA-Backups) |

Tageslimit, Makro-Ziele, Bring-Liste und Vorrat lassen sich auch in Tellerplan ändern: auf „Heute“ oben rechts das Zahnrad. Die Werte landen in denselben Optionen und erscheinen auch hier im Reiter „Konfiguration“.

Steht beim Start eine Migration an, sichert das Add-on die Datenbank vorher als `app.db.<Zeitstempel>.bak`; die letzten drei Sicherungen bleiben erhalten.
