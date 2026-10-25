"""Seite „Einkaufsliste“: zwei Wochen Plan ab heute, ohne Vorratsartikel, an Bring.

Der Knopf im Plan sendet direkt, und zwar nur Rezepte, die noch nicht gesendet
wurden; „Alles erneut senden“ schickt alle. Die Seite zeigt danach, was gesendet und
was als Vorrat übersprungen wurde. Ohne Supervisor (lokal) gibt es nur die Liste zum Kopieren.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

import clock
from db import get_session
from modules.shopping.service import ShoppingList, build_shopping_list, send_shopping_list
from supervisor import supervisor_token
from web.forms import redirect_to
from web.templating import render

router = APIRouter(prefix="/plan/shopping")
SessionDep = Annotated[Session, Depends(get_session)]

SHOPPING_DAYS = 14
STATUS_NO_SUPERVISOR = "local"
STATUS_NO_LIST = "no-list"


def _shopping_list(request: Request, session: Session, include_sent: bool = False) -> ShoppingList:
    keywords = request.app.state.settings.pantry_keywords
    return build_shopping_list(session, clock.today(), SHOPPING_DAYS, keywords, include_sent)


@router.get("", response_class=HTMLResponse)
def shopping_page(
    request: Request,
    session: SessionDep,
    sent: int | None = None,
    failed: int | None = None,
    error: str | None = None,
    status: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "plan/shopping.html",
        tab="plan",
        shopping=_shopping_list(request, session),
        list_entity=request.app.state.settings.bring_list_entity,
        sent=sent,
        failed=failed,
        error=error,
        status=status,
    )


@router.post("", response_model=None)
def shopping_send(
    request: Request, session: SessionDep, resend: Annotated[bool, Form()] = False
) -> Response:
    token = supervisor_token()
    entity_id = request.app.state.settings.bring_list_entity
    if token is None:
        return redirect_to(request, "shopping_page", query={"status": STATUS_NO_SUPERVISOR})
    if not entity_id:
        return redirect_to(request, "shopping_page", query={"status": STATUS_NO_LIST})

    shopping = _shopping_list(request, session, include_sent=resend)
    result = send_shopping_list(session, shopping, entity_id, token)
    session.commit()
    query = {"sent": str(result.sent), "failed": str(len(result.errors))}
    if result.errors:
        query["error"] = result.errors[0]
    return redirect_to(request, "shopping_page", query=query)
