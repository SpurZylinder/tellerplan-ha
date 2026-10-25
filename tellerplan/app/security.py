"""Zugriffsregeln je Port.

- Ingress-Port: kein eigenes Login; im Add-on nur Anfragen vom Ingress-Proxy
  von Home Assistant, damit andere Add-ons im internen Netz nicht hineinkommen.
- API-Port: `/api/…` nur mit `Authorization: Bearer <api_token>`; alle anderen
  Pfade sind die Vollbild-App, deren Seiten die Anmeldung über Home Assistant
  verlangen (`web.access.require_login`).
"""

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from settings import Settings
from supervisor import supervisor_token

API_PREFIX = "/api/"
INGRESS_PATH_HEADER = "x-ingress-path"
# Absender aller Ingress-Anfragen im internen Netz von Home Assistant
INGRESS_PROXY_IP = "172.30.32.2"


class PortAccessMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if _server_port(scope) == self.settings.api_port:
            rejection = self._reject_api_request(scope)
        else:
            rejection = _reject_foreign_ingress(scope)
            _apply_ingress_root_path(scope)
        if rejection is not None:
            await rejection(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _reject_api_request(self, scope: Scope) -> JSONResponse | None:
        """Antwort für unzulässige API-Anfragen; Seiten der Vollbild-App gehen durch."""
        if not scope["path"].startswith(API_PREFIX):
            return None
        if not self.settings.api_token:
            return JSONResponse({"detail": "API-Token ist nicht konfiguriert"}, status_code=503)
        if not _has_valid_token(Headers(scope=scope), self.settings.api_token):
            return JSONResponse(
                {"detail": "Ungültiger oder fehlender Token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


def _reject_foreign_ingress(scope: Scope) -> PlainTextResponse | None:
    """Im Add-on darf nur Home Assistant den Ingress-Port ansprechen; lokal jeder."""
    if supervisor_token() is None:
        return None
    client = scope.get("client")
    if client is not None and client[0] == INGRESS_PROXY_IP:
        return None
    return PlainTextResponse("Nur über Home Assistant erreichbar", status_code=403)


def _server_port(scope: Scope) -> int | None:
    server = scope.get("server")
    return server[1] if server else None


def _has_valid_token(headers: Headers, expected: str) -> bool:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token.encode(), expected.encode())


def _apply_ingress_root_path(scope: Scope) -> None:
    """Setzt den Ingress-Präfix als root_path, damit erzeugte URLs stimmen.

    Laut ASGI enthält `path` den `root_path`; Starlette schneidet ihn beim Routing
    wieder ab. Home Assistant schickt den Pfad ohne Präfix, also wird er ergänzt.
    Ohne das findet z. B. die eingehängte `/static`-App ihre Dateien nicht.
    """
    ingress_path = Headers(scope=scope).get(INGRESS_PATH_HEADER)
    if not ingress_path:
        return
    root_path = ingress_path.rstrip("/")
    scope["root_path"] = root_path
    if not scope["path"].startswith(root_path + "/"):
        scope["path"] = root_path + scope["path"]
        if scope.get("raw_path") is not None:
            scope["raw_path"] = root_path.encode() + scope["raw_path"]
