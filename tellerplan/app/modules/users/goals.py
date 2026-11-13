"""Tagesziele je Benutzer.

Die Vorgabeziele kommen aus den Optionen und werden vom Aufrufer übergeben; dieses
Modul kennt nur die eigenen Ziele in der Datenbank. Eine Änderung gilt ab dem Tag,
an dem sie gemacht wird; am selben Tag ersetzt sie die vorige.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.users.models import Goal


@dataclass(frozen=True)
class Goals:
    """Tagesziele: kcal-Limit und Makros in Gramm."""

    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int


@dataclass(frozen=True)
class EffectiveGoals:
    """Ziele für einen Tag und ob es eigene sind oder die Vorgabe."""

    goals: Goals
    own: bool


def _latest(session: Session, user_id: str, day: date) -> Goal | None:
    statement = (
        select(Goal)
        .where(Goal.user_id == user_id, Goal.valid_from <= day)
        .order_by(Goal.valid_from.desc())
        .limit(1)
    )
    return session.scalar(statement)


def goals_for(session: Session, user_id: str, day: date, defaults: Goals) -> EffectiveGoals:
    """Die Ziele, die für den Benutzer an diesem Tag gelten."""
    goal = _latest(session, user_id, day)
    if goal is None:
        return EffectiveGoals(defaults, own=False)
    return EffectiveGoals(Goals(goal.kcal, goal.protein_g, goal.fat_g, goal.carbs_g), own=True)


def set_goals(session: Session, user_id: str, valid_from: date, goals: Goals) -> Goal:
    """Speichert eigene Ziele ab `valid_from`; ein Eintrag desselben Tages wird ersetzt."""
    goal = session.scalar(
        select(Goal).where(Goal.user_id == user_id, Goal.valid_from == valid_from)
    )
    if goal is None:
        goal = Goal(user_id=user_id, valid_from=valid_from)
        session.add(goal)
    goal.kcal, goal.protein_g = goals.kcal, goals.protein_g
    goal.fat_g, goal.carbs_g = goals.fat_g, goals.carbs_g
    session.flush()
    return goal
