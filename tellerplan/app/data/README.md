# Daten

## bls_4_0.csv

Auszug aus dem Bundeslebensmittelschlüssel (BLS) 4.0: BLS-Code, Lebensmittelbezeichnung und
sieben Nährwerte pro 100 g (kcal, Eiweiß, Fett, verfügbare Kohlenhydrate, Ballaststoffe, Zucker,
Salz). Angaben unter der Nachweisgrenze („TR“, „<LOD“, „<LOQ“) sind als 0 übernommen, unbekannte
Werte („-“) als leer.

- Quelle: Max Rubner-Institut (2025): Bundeslebensmittelschlüssel (BLS), Version 4.0 –
  Deutsche Nährstoffdatenbank, https://blsdb.de
- Lizenz: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de)
- Änderungen: Auswahl von Spalten, Umwandlung von Excel nach CSV, Sortierung nach BLS-Code

Erzeugt mit `tools/bls_convert.py`; eingespielt durch die Migration `0005`.
