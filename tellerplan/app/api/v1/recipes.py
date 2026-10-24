"""Rezepte als JSON, z. B. für Kurzbefehle und das Ranking."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_session
from modules.recipes.service import RecipeSummary, recipe_summaries

router = APIRouter(prefix="/recipes", tags=["Rezepte"])


class RecipeOut(BaseModel):
    id: int
    title: str
    category: str | None
    servings: float
    is_favorite: bool
    source_url: str | None
    kcal_per_serving: float
    protein_g_per_serving: float
    ingredients_matched: int
    ingredients_total: int

    @classmethod
    def from_summary(cls, summary: RecipeSummary) -> RecipeOut:
        recipe = summary.recipe
        return cls(
            id=recipe.id,
            title=recipe.title,
            category=recipe.category,
            servings=recipe.servings,
            is_favorite=recipe.is_favorite,
            source_url=recipe.source_url,
            kcal_per_serving=round(summary.per_serving.kcal, 1),
            protein_g_per_serving=round(summary.per_serving.protein_g, 1),
            ingredients_matched=summary.match.matched,
            ingredients_total=summary.match.total,
        )


@router.get("")
def list_recipes(session: Annotated[Session, Depends(get_session)]) -> list[RecipeOut]:
    return [RecipeOut.from_summary(summary) for summary in recipe_summaries(session)]
