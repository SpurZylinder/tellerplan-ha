"""Tagesziele des angemeldeten Benutzers: eigene aus der Datenbank, sonst die Vorgabe."""

from datetime import date

from fastapi import Request
from sqlalchemy.orm import Session

from modules.users.goals import EffectiveGoals, Goals, goals_for
from settings import Settings
from web.access import current_user


def default_goals(settings: Settings) -> Goals:
    """Vorgabeziele aus den Optionen; gelten für alle ohne eigene Ziele."""
    return Goals(
        kcal=settings.daily_kcal_limit,
        protein_g=settings.protein_goal_g,
        fat_g=settings.fat_goal_g,
        carbs_g=settings.carbs_goal_g,
    )


def user_goals(request: Request, session: Session, day: date) -> EffectiveGoals:
    """Ziele des aktuellen Benutzers an einem Tag."""
    defaults = default_goals(request.app.state.settings)
    return goals_for(session, current_user(request).id, day, defaults)
