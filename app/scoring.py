import datetime
from app.config import settings

def composite_score(
    similarity: float,
    importance: float,
    created_at,
    mode: str = "balanced",
) -> float:
    weights = settings.scoring_modes.get(mode, settings.scoring_modes["balanced"])

    if isinstance(created_at, str):
        created_at = datetime.datetime.fromisoformat(created_at)

    now = datetime.datetime.now(datetime.timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)

    age_days = (now - created_at).days
    recency = max(0.0, 1.0 - age_days / 180)

    score = (
        weights["similarity"]  * similarity +
        weights["importance"]  * importance +
        weights["recency"]     * recency
    )
    return round(score, 4)