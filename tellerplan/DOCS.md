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
| `meal_names` | Namen der Mahlzeiten in Tagebuch und Plan |
| `ranking_protein_weight` | Startwert des Reglers Eiweiß/Kalorien in der Rezeptliste (0–1) |
| `api_token` | Token für Kurzbefehle und Skripte |
| `database_path` | Pfad der SQLite-Datenbank (Standard `/data/app.db`, Teil der HA-Backups) |

Vor jeder Migration legt das Add-on eine Kopie der Datenbank als `app.db.bak` an.
