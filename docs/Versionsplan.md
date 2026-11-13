# Versionsplan

Festgelegt am 2026-11-13 nach Release 0.5.0 (Abgleich mit Cookidoo, siehe [[Cookidoo-Sync]]). Jede Version bekommt vor der Umsetzung eine eigene Planungsnotiz nach dem Muster von [[Cookidoo-Sync]] (Recherche, Entscheidungen, Schritte mit Tests, Test auf dem Pi). Zwischenstände erscheinen als Patch-Versionen der laufenden Version (auf dem Weg zu 0.6.0 also `0.5.x`); die nächste Minor-Version wird erst gesetzt, wenn der Test auf dem Pi vollständig abgeschlossen ist.

| Version | Ziel | Hängt ab von |
| --- | --- | --- |
| 0.6.0 | Mehrere Benutzer: Tagebuch und Ziele je HA-Benutzer, dazu alle offenen Befunde | – |
| 0.7.0 | Zugriff von außerhalb des Heimnetzes | 0.6.0 (Benutzer) |
| 0.8.0 | Verbindung zu Apple Health | 0.6.0 (je Benutzer), 0.7.0 (unterwegs) |
| 0.9.0 | REWE-Warenkorb automatisch füllen | – (fachlich), Machbarkeit offen |
| 0.10.0 | Rezepte von Chefkoch und Einfach Backen importieren | – |
| 0.11.0 | Lebensmittel per Barcode importieren (Open Food Facts) | HTTPS für die Kamera (Ingress, ggf. 0.7.0) |

## Regel für Befunde

Festgelegt am 2026-11-13:

1. **Jeder neue Befund kommt in die nächste Version** (die nächste Minor-Version, die noch nicht veröffentlicht ist) und steht dort unter „Befunde“.
2. **Ausnahmen gibt es nur per Entscheidung, mit Datum:**
   - Der Befund gehört fachlich zu einer späteren Version im Plan. Dann steht er dort, mit Verweis auf die Entscheidung (Beispiel: K14 HTTPS → 0.7.0).
   - Der Befund ist kein echter Befund (bewusste Entscheidung, Idee, Frage). Dann wandert er nach „Ideen und Fragen“ oder wird mit Begründung geschlossen.
3. Ein Befund, der bis zum Release seiner Version nicht behoben ist, verschiebt sich nicht still: Vor dem Release wird entschieden, ob er die Version blockiert oder mit Begründung in die nächste wandert.

Befunde sind Fehler, Lücken und Risiken aus Reviews, Tests auf dem Pi und dem Alltag. Die Kennungen (`K…` Konzept, `C-…` Code) bleiben, neue Befunde zählen weiter (K16, C-J …).

## 0.6.0 – Mehrere Benutzer

Ausgearbeitet in [[Version-0.6.0]] (2026-11-13): zuerst die Befunde, dann Benutzer und Rollen. Nutzung auch mit HA-Benutzern ohne Admin-Rechte.

**Ziel:** Mehrere Personen im Haushalt nutzen Tellerplan über ihren eigenen Home-Assistant-Benutzer. „Heute“ (Tagebuch) und die Ziele (kcal-Limit, Eiweiß, Fett, KH) gelten je Benutzer; Lebensmittel, Rezepte, Plan und Einkaufsliste bleiben gemeinsam.

**Ansatz** (aus [[Architektur#Wünsche vom 2026-10-28]], vor der Umsetzung zu prüfen):

- Benutzer erkennen: Über Ingress setzt Home Assistant die Kopfzeilen `X-Remote-User-Id`, `X-Remote-User-Name` und `X-Remote-User-Display-Name`. Die Vollbild-App kennt den Benutzer aus der OAuth-Anmeldung (`ha_auth.py`). Ingress-Kopfzeilen nur vom Proxy `172.30.32.2` glauben (wie heute in `security.py`).
- `diary_entry.user_id` (Migration; bestehende Einträge gehören dem ersten Benutzer, der sich nach dem Update anmeldet, oder einem in den Optionen benannten).
- Tabelle `goal` je Benutzer, historisiert mit „gültig ab“: Alte Tage laufen gegen das damalige Ziel (löst K7 zum Teil).
- Regel 6 anpassen: Die Optionen liefern nur noch die Vorgabewerte für neue Benutzer; die eigenen Ziele stehen in der Datenbank und werden auf der Einstellseite gepflegt.

**Offene Fragen**

- Gilt ein Benutzer ohne eigene Ziele mit den Vorgabewerten aus den Optionen, oder muss er sie beim ersten Besuch festlegen?
- ~~Wem gehört ein Eintrag über die API?~~ Verschoben nach 0.8.0 (2026-11-13): Die API liest in 0.6.0 nur.
- Soll man fremde Tage sehen können (z. B. Haushalt gesamt) oder streng getrennt?
- Gehören „Rezept von gestern“, Vorfilter je Mahlzeit und „aus dem Plan übernehmen“ zum Benutzer? (vermutlich ja, sie lesen das Tagebuch)

**Befunde** (alle offenen aus [[Architektur#Ausbaustufen und offene Punkte]], Stand 2026-11-13; dort bleiben sie beschrieben)

| Befund | Kurz | Bezug zu 0.6.0 |
| --- | --- | --- |
| K4 | HA-Sicherung kopiert die laufende SQLite-Datenbank | Datensicherheit; vor der Migration für Benutzer erledigen |
| K6 | Planeintrag gilt nach der ersten gegessenen Portion als erledigt, keine Reste | Entschieden 2026-11-13: kein Befund, Komfort-Idee; zum Abschluss von 0.6.0 bewerten |
| K7 | Datenmodell-Doku weicht ab (`goal`, `weight`, `import_job`, `shopping` fehlt in der Übersicht) | `goal` wird jetzt gebaut; Rest der Doku nachziehen, `ingredient_alias` gibt es inzwischen |
| K8 | Zwei Schreiber für die Optionen (HA und Einstellseite) | Entfällt weitgehend, wenn Ziele in die Datenbank wandern |
| K9 | Zutat ohne Einheit zählt als Gramm | Prüfen, ob der Zeilenparser das inzwischen abdeckt; sonst beheben |
| K10 | Einkaufsliste trennt „EL“/„el“, „g“/„kg“, „Stück“/„Stk.“ | – |
| K11 | Plan zeigt heute + 14, Einkaufsliste rechnet heute + 13 | – |
| K13 | CSS und JS ohne Version im Link, iPhone behält alte Dateien | Zuletzt bei 0.4.16 aufgefallen |
| K15 | Tagebuch-Snapshot nur mit vier Nährwerten | Snapshot wird für `user_id` ohnehin angefasst |
| C-A | Senden an Bring blockiert bei hängendem Supervisor | – |
| C-C | Optionen und Wertebereiche doppelt in `settings.py` und `config.yaml` | Optionen ändern sich mit den Vorgabezielen |
| C-D | `options.json` nicht atomar geschrieben | wie bei der Token-Datei in 0.4.15 |
| C-E | `modules/shopping` importiert `supervisor` direkt | – |
| C-G | Testlücken: Datumsgrenzen in den Seiten, Coverage, echte Supervisor-Antworten | – |
| C-I | Kleinigkeiten (0 Portionen, `ShoppingItem.optional`, `options.py` vs. `/settings`) | – |
| C-H | Kein CSRF-Schutz für POST-Formulare | Mit mehreren Benutzern und Rollen wichtiger |
| K16 | Vollbild-App: Jeder HA-Benutzer darf nach der Anmeldung alles, auch Optionen und Cookidoo-Zugang (neu, 2026-11-13) | Wird mit den Rollen behoben |
| – | Braucht die Einstellseite `hassio_api`? | Beim Umbau der Einstellseite klären |

Fachlich in eine spätere Version gelegt (Entscheidung 2026-11-13, Regel 2): **K14** (Port 8099 nur HTTP) → 0.7.0, weil es erst mit Zugriff von außen ins Gewicht fällt und dort ohnehin gelöst werden muss.

## 0.7.0 – Zugriff von außerhalb

**Ziel:** Tellerplan ist unterwegs nutzbar, auf dem iPhone als Vollbild-App und für Kurzbefehle, ohne Abstriche bei der Sicherheit.

**Zu entscheiden:** der Weg nach außen.

| Weg | Vorteile | Nachteile |
| --- | --- | --- |
| Nabu Casa (Home Assistant Cloud) | Ingress samt HTTPS ohne eigenen Aufwand | Kostet; nur Ingress, nicht Port 8099 |
| VPN (Tailscale-Add-on oder Router) | Nichts offen im Internet; alles wie zu Hause | App auf jedem Gerät, VPN muss laufen (auch für Kurzbefehle) |
| Reverse Proxy mit eigener Domain und Zertifikat | Direkt erreichbar, auch für Kurzbefehle | Offen im Internet: Härtung nötig (Anmeldung, Begrenzung von Versuchen, Updates) |

**Befunde:** K14 (HTTPS für Port 8099).

**Offene Fragen:** Welcher Weg? Reicht die Anmeldung über Home Assistant für die Vollbild-App von außen? Wie lange gelten Sitzungen unterwegs?

## 0.8.0 – Apple Health

**Ziel:** Gewicht aus Apple Health in Tellerplan, gegessene Nährwerte aus Tellerplan in Apple Health.

**Rahmen:** Apple Health hat keine Schnittstelle für Server; Daten verlassen das iPhone nur über Apps oder Kurzbefehle. Weg darum über Kurzbefehle und die API auf Port 8099 (siehe Stufe 5 „Gewicht per Kurzbefehl“ in [[Architektur]]):

- Gewicht: Kurzbefehl liest das letzte Gewicht aus Health und schickt es an die API (Tabelle `weight`, schon im Datenmodell vorgesehen).
- Nährwerte: Kurzbefehl holt die Tageswerte aus dem Tagebuch und schreibt sie als „Nahrungsenergie“, Eiweiß usw. nach Health. Doppelte Einträge bei mehrfachem Lauf vermeiden.
- Automatisch über eine Automation in der Kurzbefehle-App (z. B. abends), je Benutzer mit eigenem Token: Die API bekommt hier Tokens je Benutzer (Tabelle, nur als Hash gespeichert, in den Einstellungen erzeugen und widerrufen), weil sie erstmals ins Tagebuch schreibt (aus 0.6.0 verschoben, 2026-11-13).

**Offene Fragen:** Wohin zeigt das Gewicht in Tellerplan (Verlauf, Einfluss auf Ziele)? Welche Nährwerte gehen nach Health?

## 0.9.0 – REWE-Warenkorb

**Ziel:** Aus der Einkaufsliste (ohne Vorrat) entsteht ein REWE-Warenkorb mit den Standardprodukten der Grundzutaten, zur Abholung.

**Grundlage:** `food.rewe_id` (0.4.14), Standardprodukte an Grundzutaten, Einkaufsliste (`modules/shopping`), Werkzeuge `tools/rewe_fetch.py` und `tools/rewe_har_extract.py`.

**Zuerst Machbarkeit klären** (wie Schritt 1 bei [[Cookidoo-Sync]]): REWE hat keine öffentliche Schnittstelle für den Warenkorb. **Achtung:** REWE lehnt automatisierte Abrufe ab (403), und es ist festgelegt, diese Sperre nicht zu umgehen ([[Architektur]], Abschnitt REWE-Produkte). Ein automatischer Warenkorb muss also einen erlaubten Weg finden, sonst bleibt nur der Rückfall. Zu prüfen: inoffizielle Schnittstelle der REWE-App oder -Seite (Anmeldung, Captcha, Nutzungsbedingungen), Mengen umrechnen (Gramm → Packungen), nicht verfügbare Artikel. Rückfall, falls das nicht tragfähig ist: Liste mit Links zu den Produktseiten zum schnellen Abarbeiten.

## 0.10.0 – Rezepte von Chefkoch und Einfach Backen

**Ziel:** Rezepte von chefkoch.de und einfachbacken.de lassen sich über ihren Link importieren, so wie Cookidoo-Rezepte: Titel, Standardportionen, Link, Quell-ID und rohe Zutatenzeilen, danach Zuordnen wie gewohnt.

**Rahmen:**

- Regel 2 gilt: Nährwertangaben der Seiten nur als Vergleichswert (`recipe_reference`), nie in der Rechnung.
- Ein Importer je Quelle unter `modules/importers` (wie `cookidoo_page.py`), reine Logik von Seite zu Entwurf; der Abruf der Seite liegt außerhalb des Fachmoduls (wie `cookidoo.py`), gedrosselt, mit Größen- und Zeitgrenze, nur über den geprüften Link der jeweiligen Seite.
- Zeilenparser und gelernte Zuordnungen bleiben gleich; Unterschiede im Zeilenformat der Seiten im Parser abfangen, nicht im Importer.

**Zuerst prüfen** (offener Punkt aus [[Architektur#Ausbaustufen und offene Punkte]]): Liefern beide Seiten strukturierte Daten (JSON-LD `schema.org/Recipe` mit `recipeIngredient` und `recipeYield`)? Wie sehen Links und IDs aus? Was sagen die Nutzungsbedingungen zum Abruf einzelner Rezepte für den eigenen Gebrauch?

**Offene Fragen:** Eingabe über das Teilen-Menü (Kurzbefehl, sinnvoll ab 0.7.0) oder nur Link einfügen in den Einstellungen? Kategorie übernehmen oder wie bei Cookidoo selbst wählen?

## 0.11.0 – Lebensmittel per Barcode

**Ziel:** Ein Markenprodukt lässt sich per Barcode als Lebensmittel anlegen: Kamera auf dem iPhone oder Nummer eintippen, Nährwerte pro 100 g von Open Food Facts, danach wie jedes Lebensmittel nutzbar (Grundzutat, Eintragen, Zuordnen).

**Rahmen:**

- Nur einzelne Produkte auf Abruf, nicht die ganze Datenbank (Vorschlag vom 2026-10-25: mehrere Millionen Produkte, schwankende Qualität, ODbL). `food.source = off`, Barcode als Quell-ID und im eindeutigen Feld `food.barcode` (Migration 0012 „Barcode und Packung“): Ein Produkt, das es schon gibt (z. B. aus dem REWE-Import), wird erkannt und nicht doppelt angelegt.
- Nährwerte landen an `food` (Regel 1); vor dem Speichern anzeigen und bearbeitbar machen, weil die Daten von Open Food Facts lückenhaft sein können. Quelle und Lizenz (ODbL) nennen.
- Kamera im Browser braucht HTTPS: über Ingress gegeben, unterwegs über den Weg aus 0.7.0. Erkennen mit der Barcode-API des Browsers, wo verfügbar, sonst eingetippte Nummer.

**Offene Fragen:** Unterstützt Safari auf dem iPhone die Barcode-Erkennung im Browser, oder braucht es eine kleine Bibliothek (ohne Frontend-Build, also als einzelne Datei unter `static/vendor`)? Produkt auch direkt beim Eintragen auf „Heute“ scannen? Was, wenn Open Food Facts das Produkt nicht kennt (manuell anlegen mit Barcode)?

## Nicht eingeplant

Aus [[Architektur#Ausbaustufen und offene Punkte]], ohne Version bis zur nächsten Planung:

- Stufe 4, Rest: Freitext-Import; Kurzbefehl „Teilen“ aus der Cookidoo-App an die API (sinnvoll ab 0.7.0)
- Cookidoo: Anmeldung über den Browser (wartet auf eine neue Version von `cookidoo-api`), Einkaufsliste an Cookidoo statt Bring
- Ideen und Fragen: Kontrollseite vor dem Senden an Bring, Einkaufshistorie aus REWE-Bestellungen, Konfigset für Grundzutaten, Kochschritte von Cookidoo, Synonyme AT/CH, Zusätze im Zeilenparser, Zuordnen-Seite nach Nutzen sortieren
