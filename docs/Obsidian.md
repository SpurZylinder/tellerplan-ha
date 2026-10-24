# Obsidian-Vault

Die Doku wird mit Obsidian gepflegt. Geöffnet wird der **Repo-Ordner** als Vault, sichtbar ist aber nur `docs/`.

## Wie das funktioniert

| Einstellung | Datei | Wirkung |
| --- | --- | --- |
| Ausgeschlossene Dateien `/^(?!docs(\/\|$)).*/` | `.obsidian/app.json` | Alles außerhalb von `docs/` fehlt in Suche, Graph, Schnellwechsler und Linkvorschlägen |
| CSS-Snippet `nur-docs` | `.obsidian/snippets/nur-docs.css` | Blendet im Dateibaum alles außer `docs/` aus |
| Neue Notizen | `.obsidian/app.json` | landen in `docs/` |
| Anhänge | `.obsidian/app.json` | landen in `docs/assets/` |
| Tägliche Notizen | `.obsidian/daily-notes.json` | landen in `docs/Journal/` |
| Vorlagen | `.obsidian/templates.json` | liegen in `docs/Vorlagen/` |
| Excalidraw | Plugin-Einstellungen | Zeichnungen, Bibliotheken und Skripte unter `docs/Excalidraw/` |

Code-Dateien bleiben trotzdem verlinkbar über normale Markdown-Links, z. B. `[settings.py](../tellerplan/app/settings.py)`.

## Was im Git liegt

- Geteilte Einstellungen: `app.json`, `appearance.json`, `core-plugins.json`, `community-plugins.json`, Snippets, Plugin-`data.json`
- Nicht versioniert: `workspace*.json` (Fensterlayout), Plugin-Code (`main.js`, `styles.css`)

Auf einem neuen Rechner deshalb Excalidraw einmal über *Community-Plugins* installieren; die Einstellungen kommen aus dem Repo.
