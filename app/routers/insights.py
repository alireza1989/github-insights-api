import time
from collections import defaultdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_app_settings, get_session
from app.github.utils import normalize_repo
from app.insights.service import generate_insight
from app.routers.metrics import _get_repo, cycle_time, review_load
from app.schemas.insights import InsightResponse

router = APIRouter(tags=["insights"])

# Simple in-memory per-IP token bucket (rate limits the costly LLM endpoint)
_buckets: dict[str, list[float]] = defaultdict(list)
_last_eviction: float = 0.0


def _check_rate_limit(ip: str, limit_per_minute: int) -> None:
    global _last_eviction
    now = time.time()

    # Sweep IPs whose entire window has expired every 5 minutes to prevent unbounded growth.
    if now - _last_eviction > 300:
        stale = [k for k, v in list(_buckets.items()) if not any(now - t < 60 for t in v)]
        for k in stale:
            del _buckets[k]
        _last_eviction = now

    window = [t for t in _buckets[ip] if now - t < 60]
    if len(window) >= limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit_per_minute} insights/minute per IP.",
        )
    window.append(now)
    _buckets[ip] = window


@router.get("/insights", response_model=InsightResponse)
async def get_insight(
    request: Request,
    repo: str = Query(..., description="Repository as 'owner/name' or a full GitHub URL"),
    from_date: date = Query(..., alias="from", description="Start date (inclusive)"),
    to_date: date = Query(..., alias="to", description="End date (inclusive)"),
    metric: Literal["review-load"] = Query("review-load", description="Metric to analyse"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InsightResponse:
    """
    Generate an LLM-powered narrative insight over the requested metric.

    The response includes a narrative, an optional root-cause hypothesis,
    a deterministically computed confidence score, and an evidence chain.
    Results are cached for 24 hours.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip, settings.rate_limit_per_minute)
    repo = normalize_repo(repo)

    # Fetch review-load (required) and cycle-time (best-effort: may have no merged PRs)
    metrics = await review_load(
        repo=repo,
        from_date=from_date,
        to_date=to_date,
        top=10,
        session=session,
    )

    try:
        ct_metrics = await cycle_time(repo=repo, from_date=from_date, to_date=to_date, session=session)
    except HTTPException:
        ct_metrics = None

    return await generate_insight(metrics, session, settings, metric=metric, cycle_time=ct_metrics)
