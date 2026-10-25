# Datenpflege

Wie Rezepte und Lebensmittel in die Datenbank kommen und wie man sie später erweitert. Alles läuft am Rechner; der Pi nimmt nur fertige Dateien an (Einstellungen → „Importieren“). Hintergrund und Regeln stehen in [[Architektur]], Einrichten und Release in [[Entwicklung]].

## Überblick

| Was | Quelle | Werkzeug | Ergebnis (in `dev/`) |
| --- | --- | --- | --- |
| Rezepte | Cookidoo-Sammlung (JSON aus dem Ranking-Widget) | `tools/cookidoo_fetch.py` | `cookidoo/…_entwuerfe.json` (Format `tellerplan-recipes`) |
| Markenprodukte | REWE-Favoriten und -Produktseiten aus dem Browser, Open Food Facts | `tools/rewe_har_extract.py`, `tools/rewe_fetch.py` | `Rewe/rewe_lebensmittel.json` (Format `tellerplan-foods`) |
| Grundzutaten wie Apfel, Zwiebel, Mehl | BLS 4.0 | bereits in der Datenbank (Migration 0005) | – |

Der Ordner `dev/` ist nicht im Git. Zwischenspeicher (`cookidoo/pages/`, `Rewe/pages/`, `Rewe/off/`) bleiben liegen, damit ein erneuter Lauf nichts doppelt abruft.

## Rezepte aus Cookidoo

1. Sammlung als JSON nach `dev/cookidoo/` legen (Felder `ID`, `Titel`, `Kategorie`, `Portionen`, `URL` …).
2. Entwürfe erzeugen – lädt die öffentlichen Rezeptseiten gedrosselt und nimmt nur die Zutatenzeilen:
   ```bash
   python tools/cookidoo_fetch.py dev/cookidoo/<sammlung>.json dev/cookidoo/<sammlung>_entwuerfe.json
   ```
3. In Tellerplan hochladen (siehe unten). Nährwerte aus Cookidoo werden nur als Vergleich gespeichert, nie gerechnet.

## Markenprodukte aus REWE

REWE lehnt automatisierte Abrufe ab (403); diese Sperre wird nicht umgangen. Die Seiten kommen daher aus dem eigenen Browser.

**Mitschnitt aufnehmen**

1. In Firefox ein **privates Fenster** öffnen (Strg+Umschalt+P), **nicht** bei REWE anmelden – die Produktseiten sind öffentlich. So landen weder Konto-Cookies noch Bestellungen oder Telefonnummer im Mitschnitt.
2. Die Linkliste `dev/Rewe/rewe_lebensmittel_offen.html` in diesem Fenster öffnen.
3. F12 → „Netzwerkanalyse“, im Zahnrad-Menü **„Logs beibehalten“** einschalten (sonst löscht Firefox das Protokoll bei jedem Seitenwechsel). Optional Filter „HTML“, um die Datei klein zu halten.
4. Links nacheinander im selben Tab öffnen, mit Alt+← zurück. Am meisten bringen Produkte, die als Standard hinter einer Grundzutat stehen sollen (Milch, Joghurt, Käse …); Drogerie und loses Obst überspringen.
5. Rechtsklick in die Anfrageliste → „Alle als HAR speichern“, Datei nach `dev/Rewe/`.

Alternativ Edge/Chrome: neuere Versionen exportieren HAR-Dateien standardmäßig bereinigt, ohne `Cookie`-, `Set-Cookie`- und `Authorization`-Header.

**Auswerten**

```bash
python tools/rewe_har_extract.py          # neueste .har in dev/Rewe/
python tools/rewe_fetch.py dev/Rewe/rewe_json/rewe_favoriten.json dev/Rewe/rewe_lebensmittel.json
```

- `rewe_har_extract.py` liest nur eine feste Feldliste: Favoriten (einmal), Bestellpositionen (Titel, EAN, Menge, Kategorie) und Produktseiten (nach `dev/Rewe/pages/`). Preise, Kennungen, Telefonnummer, Kommentare und Adressen werden verworfen; ein Selbsttest bricht ab, falls doch etwas davon in einer Ausgabe landet. Auch gekürzte, ungültige HAR-Dateien gehen.
- `rewe_fetch.py` nimmt Nährwerte aus den gespeicherten Produktseiten, sonst über den Barcode aus Open Food Facts (gedrosselt, Pause bei „zu viele Anfragen“). Was noch fehlt, steht wieder in der Linkliste.
- **Danach die HAR-Datei löschen.** Sie enthält Cookies, bei angemeldeter Sitzung auch Bestelldaten.

Die Favoriten (`rewe_favoriten.json`) stammen aus einem Mitschnitt mit Anmeldung, weil REWE sie nur angemeldet ausliefert. Neue Favoriten erfordern also einmal einen angemeldeten Mitschnitt – danach die Datei sofort löschen.

## In Home Assistant übernehmen

1. Läuft auf dem Pi eine ältere Version, zuerst aktualisieren (Apps → Tellerplan → Aktualisieren). Migrationen laufen beim Start; vorher sichert das Add-on die Datenbank (`app.db.<Zeitstempel>.bak`, die letzten drei bleiben).
2. In Tellerplan Einstellungen → **Importieren**, am besten am Rechner (über die HA-Seitenleiste oder `http://<IP>:8099/`):
   1. zuerst **Lebensmittel**: `dev/Rewe/rewe_lebensmittel.json`
   2. dann **Rezepte**: `dev/cookidoo/<sammlung>_entwuerfe.json`

   Die Datei sagt selbst, was sie enthält. Ein erneuter Import legt nichts doppelt an: Lebensmittel werden am Barcode erkannt und aktualisiert (Kurzname und eigene Einheiten bleiben), Rezepte an Quelle und ID (Zutaten und Zuordnungen bleiben).
3. **Zuordnen** (Rezepte → „Zuordnen“), von oben nach unten:
   - Gewürze, Salz, Wasser: Haken „ohne Nährwerte“
   - Grundzutaten mit eigenen Produkten als Standard, z. B. „Milch“ → Berchtesgadener Bio-Milch
   - übrige mit BLS-Produkten, zuletzt „Ohne Produkt“ und „Einheiten“

## Später erweitern

- **Weitere REWE-Produkte:** neuen Mitschnitt nach obigem Muster, beide Skripte ausführen, `rewe_lebensmittel.json` erneut hochladen. Vorhandene Produkte werden aktualisiert, neue kommen hinzu.
- **Weitere Rezepte:** neue Sammlung oder ergänzte Sammlung durch `cookidoo_fetch.py`, Entwürfe hochladen; bekannte Zutatennamen bringen ihre Grundzutat gleich mit.
- **Eigenes Produkt von Hand:** Lebensmittel → „+ Neu“ mit Hersteller und Nährwerten von der Packung.

## Stand 2026-10-26

- 172 Cookidoo-Rezepte mit 2.529 Zutatenzeilen als Entwürfe
- 185 REWE-Favoriten; 80 davon mit Nährwerten (57 aus Produktseiten, 23 aus Open Food Facts), 104 noch in der Linkliste
- Offen: Einkaufshistorie aus REWE-Bestellungen (siehe [[Architektur#Ausbaustufen und offene Punkte]])
