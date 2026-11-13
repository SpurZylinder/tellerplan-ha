"""Benutzer von Tellerplan: die Home-Assistant-Benutzer, die Tellerplan schon geöffnet haben.

Anmeldung und Rollen kommen aus Home Assistant; Tellerplan merkt sich nur, wen es
kennt (für das Tagebuch je Benutzer und die Zuordnung alter Einträge).
"""

from modules.users import models

__all__ = ["models"]
