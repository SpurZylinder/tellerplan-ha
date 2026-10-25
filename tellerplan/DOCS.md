# Tellerplan

Kalorien zählen, Rezepte verwalten und die Woche planen – direkt in Home Assistant.

## Zugang

- **Oberfläche:** über die Seitenleiste (Ingress), ohne eigenes Login.
- **API:** Port 8099, nur mit `Authorization: Bearer <api_token>`. Ohne gesetzten Token ist die API gesperrt.

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
| `api_token` | Token für Kurzbefehle und Skripte |
| `database_path` | Pfad der SQLite-Datenbank (Standard `/data/app.db`, Teil der HA-Backups) |

Tageslimit, Makro-Ziele, Bring-Liste und Vorrat lassen sich auch in Tellerplan ändern: auf „Heute“ oben rechts das Zahnrad. Die Werte landen in denselben Optionen und erscheinen auch hier im Reiter „Konfiguration“.

Steht beim Start eine Migration an, sichert das Add-on die Datenbank vorher als `app.db.<Zeitstempel>.bak`; die letzten drei Sicherungen bleiben erhalten.
