"""Seite „Einkaufsliste“: zwei Wochen Plan ab heute, ohne Vorratsartikel, an Bring.

Der Knopf im Plan startet das Senden im Hintergrund und zeigt sofort den Fortschritt;
die Seite fragt den Stand alle zwei Sekunden ab und zeigt am Ende das Ergebnis
(Befund K18: Vorher wartete der Klick, bis jeder Artikel bei Bring war, und der Browser
gab bei vielen Artikeln vorher auf). Solange gesendet wird, startet ein weiterer Klick
nichts Neues (Befund K19). Gesendet werden nur Rezepte, die noch nicht gesendet wurden;
„Alles erneut senden“ schickt alle. Ohne Supervisor (lokal) gibt es nur die Liste zum Kopieren.

„Bring-Liste prüfen“ liest nur: Funktionen der Liste und ihre offenen Einträge, als
Grundlage dafür, vorhandene Artikel künftig zu erweitern statt neu anzulegen.
"""

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

import clock
from db import get_session
from modules.planner.service import plan_horizon
from modules.shopping.service import (
    AddItem,
    SendError,
    SendResult,
    ShoppingList,
    build_shopping_list,
    send_shopping_list,
)
from supervisor import (
    SupervisorError,
    call_service,
    call_service_with_response,
    get_core_state,
    supervisor_token,
)
from web.forms import redirect_to
from web.templating import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/shopping")
SessionDep = Annotated[Session, Depends(get_session)]

# Frist je Artikel; hängt Home Assistant, ist das Senden trotzdem nach absehbarer Zeit fertig
ITEM_TIMEOUT_SECONDS = 5.0
STATUS_NO_SUPERVISOR = "local"
STATUS_NO_LIST = "no-list"
# So oft fragt die Seite während des Sendens nach dem Stand
POLL_SECONDS = 2
# Funktionen einer To-do-Liste in Home Assistant (TodoListEntityFeature)
TODO_FEATURES = {
    1: "Anlegen",
    2: "Löschen",
    4: "Ändern",
    8: "Verschieben",
    16: "Fälligkeitsdatum",
    32: "Fälligkeit mit Uhrzeit",
    64: "Beschreibung",
}
# So viele Zeichen der Rohantwort zeigt die Prüfung zum Kopieren
RAW_RESPONSE_LIMIT = 4000
# So viele offene Einträge zeigt die Prüfung als Beispiel
SAMPLE_ITEMS = 5

# Schützt das Starten: zwei Klicke gleichzeitig starten höchstens ein Senden
_start_lock = threading.Lock()


@dataclass
class SendJob:
    """Stand eines Sendens im Hintergrund; liegt in `app.state.shopping_job`."""

    target: str
    total: int = 0
    sent: int = 0
    done: bool = False
    result: SendResult | None = None
    error: str | None = None


@dataclass(frozen=True)
class BringCheck:
    """Ergebnis von „Bring-Liste prüfen“ (nur lesend)."""

    entity_id: str
    features: list[str] = field(default_factory=list)
    feature_flags: int | None = None
    open_items: list[dict[str, Any]] = field(default_factory=list)
    raw: str = ""
    error: str | None = None


def todo_list_sender(entity_id: str, token: str) -> AddItem:
    """Sendet Artikel per `todo.add_item` an eine To-do-Liste in Home Assistant (z. B. Bring)."""

    def add_item(name: str, description: str) -> None:
        data = {"entity_id": entity_id, "item": name}
        if description:
            data["description"] = description
        try:
            call_service("todo", "add_item", data, token, timeout=ITEM_TIMEOUT_SECONDS)
        except SupervisorError as error:
            raise SendError(str(error)) from error

    return add_item


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="einkaufsliste", daemon=True).start()


def _job(app: FastAPI) -> SendJob | None:
    return getattr(app.state, "shopping_job", None)


def _shopping_list(request: Request, session: Session, include_sent: bool = False) -> ShoppingList:
    keywords = request.app.state.settings.pantry_keywords
    first, last = plan_horizon(clock.today())
    return build_shopping_list(session, first, last, keywords, include_sent)


def _run_send(app: FastAPI, job: SendJob, token: str, include_sent: bool) -> None:
    """Sendet im Hintergrund mit eigener Datenbank-Sitzung und hält `job` aktuell."""
    try:
        with app.state.session_factory() as session:
            first, last = plan_horizon(clock.today())
            keywords = app.state.settings.pantry_keywords
            shopping = build_shopping_list(session, first, last, keywords, include_sent)
            job.total = len(shopping.items)
            sender = todo_list_sender(job.target, token)

            def progress(sent: int) -> None:
                job.sent = sent

            job.result = send_shopping_list(session, shopping, sender, job.target, progress)
            session.commit()
    except Exception:
        logger.exception("Einkaufsliste: Senden abgebrochen")
        job.error = "Das Senden ist unerwartet abgebrochen; Details im Protokoll des Add-ons."
    finally:
        job.done = True


def _finished_message(job: SendJob) -> dict[str, Any]:
    """Werte für die Ergebnismeldung; danach ist der Auftrag erledigt und wird vergessen."""
    result = job.result
    return {
        "sent": result.sent if result else 0,
        "failed": result.not_sent if result else job.total,
        "error": job.error or (result.errors[0] if result and result.errors else None),
    }


@router.get("", response_class=HTMLResponse)
def shopping_page(request: Request, session: SessionDep, status: str | None = None) -> HTMLResponse:
    job = _job(request.app)
    message: dict[str, Any] = {"sent": None, "failed": None, "error": None}
    if job is not None and job.done:
        message = _finished_message(job)
        request.app.state.shopping_job = None
    return render(
        request,
        "plan/shopping.html",
        tab="plan",
        shopping=_shopping_list(request, session),
        list_entity=request.app.state.settings.bring_list_entity,
        job=job if job is not None and not job.done else None,
        poll_seconds=POLL_SECONDS,
        status=status,
        can_check=supervisor_token() is not None,
        **message,
    )


@router.get("/status", response_class=HTMLResponse)
def shopping_status(request: Request) -> Response:
    """Fortschritt für die Seite; ist das Senden fertig, lädt sie neu und zeigt das Ergebnis."""
    job = _job(request.app)
    if job is None or job.done:
        return Response(status_code=200, headers={"HX-Refresh": "true"})
    return render(request, "plan/_shopping_job.html", job=job, poll_seconds=POLL_SECONDS)


@router.post("", response_model=None)
def shopping_send(request: Request, resend: Annotated[bool, Form()] = False) -> Response:
    token = supervisor_token()
    entity_id = request.app.state.settings.bring_list_entity
    if token is None:
        return redirect_to(request, "shopping_page", query={"status": STATUS_NO_SUPERVISOR})
    if not entity_id:
        return redirect_to(request, "shopping_page", query={"status": STATUS_NO_LIST})

    app = request.app
    with _start_lock:
        running = _job(app)
        if running is None or running.done:
            job = SendJob(target=entity_id)
            app.state.shopping_job = job
            run = getattr(app.state, "run_in_background", _start_thread)
            run(lambda: _run_send(app, job, token, resend))
        else:
            logger.info("Einkaufsliste: Senden läuft schon, kein zweiter Start")
    return redirect_to(request, "shopping_page")


def check_bring_list(entity_id: str, token: str) -> BringCheck:
    """Liest Funktionen und offene Einträge der Liste; ändert nichts."""
    try:
        state = get_core_state(entity_id, token)
        flags = state.get("attributes", {}).get("supported_features")
        response = call_service_with_response(
            "todo", "get_items", {"entity_id": entity_id, "status": "needs_action"}, token
        )
    except SupervisorError as error:
        return BringCheck(entity_id=entity_id, error=str(error))
    items = response.get(entity_id, {}).get("items", [])
    features = (
        [name for bit, name in TODO_FEATURES.items() if flags & bit]
        if isinstance(flags, int)
        else []
    )
    raw = json.dumps(
        {"supported_features": flags, "service_response": response}, ensure_ascii=False, indent=2
    )
    return BringCheck(
        entity_id=entity_id,
        features=features,
        feature_flags=flags if isinstance(flags, int) else None,
        open_items=[item for item in items if isinstance(item, dict)][:SAMPLE_ITEMS]
        if isinstance(items, list)
        else [],
        raw=raw[:RAW_RESPONSE_LIMIT],
    )


@router.post("/check", response_class=HTMLResponse)
def shopping_check(request: Request, session: SessionDep) -> HTMLResponse:
    token = supervisor_token()
    entity_id = request.app.state.settings.bring_list_entity
    if token is None or not entity_id:
        status = STATUS_NO_SUPERVISOR if token is None else STATUS_NO_LIST
        return shopping_page(request, session, status=status)
    check = check_bring_list(entity_id, token)
    logger.info(
        "Bring-Liste geprüft: Funktionen %s, %d offene Einträge gelesen, Fehler: %s",
        check.feature_flags,
        len(check.open_items),
        check.error or "keiner",
    )
    return render(
        request,
        "plan/shopping.html",
        tab="plan",
        shopping=_shopping_list(request, session),
        list_entity=entity_id,
        job=None,
        poll_seconds=POLL_SECONDS,
        status=None,
        can_check=True,
        check=check,
        sent=None,
        failed=None,
        error=None,
    )
