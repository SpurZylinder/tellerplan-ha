"""Zugriffsregeln je Port.

- Ingress-Port: nur über den Home-Assistant-Ingress erreichbar, kein eigenes Login.
- API-Port: nur `/api/…` und nur mit `Authorization: Bearer <api_token>`.
"""

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from settings import Settings

API_PREFIX = "/api/"
INGRESS_PATH_HEADER = "x-ingress-path"


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
            if rejection is not None:
                await rejection(scope, receive, send)
                return
        else:
            _apply_ingress_root_path(scope)

        await self.app(scope, receive, send)

    def _reject_api_request(self, scope: Scope) -> JSONResponse | None:
        """Antwort für unzulässige Anfragen am API-Port, sonst None."""
        if not scope["path"].startswith(API_PREFIX):
            return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)
        if not self.settings.api_token:
            return JSONResponse({"detail": "API-Token ist nicht konfiguriert"}, status_code=503)
        if not _has_valid_token(Headers(scope=scope), self.settings.api_token):
            return JSONResponse(
                {"detail": "Ungültiger oder fehlender Token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


def _server_port(scope: Scope) -> int | None:
    server = scope.get("server")
    return server[1] if server else None


def _has_valid_token(headers: Headers, expected: str) -> bool:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token.encode(), expected.encode())


def _apply_ingress_root_path(scope: Scope) -> None:
    """Setzt den Ingress-Präfix als root_path, damit erzeugte URLs stimmen."""
    ingress_path = Headers(scope=scope).get(INGRESS_PATH_HEADER)
    if ingress_path:
        scope["root_path"] = ingress_path.rstrip("/")
