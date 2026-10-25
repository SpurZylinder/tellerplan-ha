# Tellerplan – Dokumentation

Einstieg in die Projektdoku. Dieser Ordner ist der sichtbare Teil des Obsidian-Vaults.

## Notizen

- [[Architektur]] – Ziele, Module, Datenmodell, Abläufe, Ausbaustufen
- [[Entwicklung]] – lokal einrichten, starten, prüfen, migrieren, veröffentlichen
- [[Obsidian]] – wie dieser Vault eingerichtet ist
- [[Sichtbarkeit]] – warum Repo und Image öffentlich sind und wie es privat ginge

## Stand

Stufe 1 ist fertig, Stufe 2 und 3 stehen in einer Grundversion. Als Nächstes: erstes Release und Live-Betrieb auf dem Raspberry Pi, Feinschliff nach dem iPhone-Test, danach Stufe 4 (Importe). Reihenfolge siehe [[Architektur#Ausbaustufen und offene Punkte]].

- [x] Repo-Gerüst, Home-Assistant-Add-on-Struktur
- [x] FastAPI-App mit zentralen Einstellungen (`settings.py`)
- [x] SQLite + Alembic mit automatischer Migration beim Start
- [x] CI (Ruff + pytest) und Release (arm64-Image nach GHCR)
- [x] UI-Rahmen mit Tab-Leiste (Heute · Plan · Rezepte), Einstellungen über das Zahnrad auf „Heute“
- [x] Lebensmittel anlegen, suchen, Einheiten pflegen; Demo-Set
- [x] Nährwertrechnung (`modules/nutrition`)
- [x] Rezepte: Liste im Ranking-Look, Detail, Anlegen, Zutaten aus den Lebensmitteln
- [x] Kochansicht mit Schritten und mitlaufenden Zutaten; Link „In Cookidoo öffnen“
- [x] Plan: Spalten oder Liste, drei Tage zurück und zwei Wochen voraus, Rezepte verschieben
- [x] Heute als Tages-Dashboard: Halbkreis mit Rest kcal, Makro-Balken, Eintragen pro Mahlzeit, Übernahme aus dem Plan
- [x] BLS 4.0: 7.140 Lebensmittel, Suche mit Ranking und unscharfer Suche, Demo-Rezepte auf BLS-Basis
- [x] Einkaufsliste: zwei Wochen Plan ab heute, ohne Vorratsartikel, über die HA-Integration an Bring
- [x] Einstellseite in der App: kcal-Limit und Makro-Ziele, gespeichert in den Add-on-Optionen
- [ ] Erstes Release `v0.1.0` (Release-Workflow lief noch nie)
- [ ] Live-Betrieb in Home Assistant auf dem Raspberry Pi
- [ ] Importe: Freitext, Zeilenparser, Matching mit Alias-Lernen, Cookidoo (Stufe 4)
