"""Seite „Heute“: Tageslimit und die für heute geplanten Gerichte."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from db import get_session
from modules.planner.service import plan_days
from web.templating import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def today_page(request: Request, session: Annotated[Session, Depends(get_session)]) -> HTMLResponse:
    settings = request.app.state.settings
    (today,) = plan_days(session, date.today(), 1, settings.meal_names)
    return render(
        request,
        "today.html",
        tab="today",
        today=today,
        daily_kcal_limit=settings.daily_kcal_limit,
    )
