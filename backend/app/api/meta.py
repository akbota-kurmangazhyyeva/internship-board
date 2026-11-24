from fastapi import APIRouter

from app.extraction.vocab import CITY_NAMES, SKILL_NAMES
from app.schemas import FiltersMeta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/filters", response_model=FiltersMeta)
def filter_options() -> FiltersMeta:
    """Values the web app can offer in filter and profile forms."""
    return FiltersMeta(
        cities=CITY_NAMES,
        skills=sorted(SKILL_NAMES, key=str.lower),
        levels=["intern", "junior", "mid", "senior"],
        work_formats=["remote", "hybrid", "onsite"],
        languages=["kk", "ru", "en"],
        sorts=["relevance", "newest", "deadline", "fit"],
    )
