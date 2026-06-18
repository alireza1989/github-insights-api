"""
Insight service: orchestrates metrics → confidence → LLM → grounding → cache.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.insights.confidence import compute_confidence
from app.insights.grounding import check_grounding
from app.insights.llm import call_llm
from app.insights.prompts import get_prompt
from app.logging_config import get_logger
from app.models.insight_cache import InsightCache
from app.schemas.insights import (
    ConfidenceScore,
    EvidenceItem,
    InsightResponse,
    InsightToolInput,
    ModelInfo,
)
from app.schemas.metrics import CycleTimeResponse, ReviewLoadResponse

logger = get_logger(__name__)

_CACHE_TTL_HOURS = 24
_PROMPT_NAME = "insights"
_PROMPT_VERSION = 2


def _cache_key(repo: str, from_date: str, to_date: str, metric: str, model: str) -> str:
    # Prompt version is part of the key so cached entries auto-invalidate when prompts change.
    raw = f"{repo}|{from_date}|{to_date}|{metric}|{model}|v{_PROMPT_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_evidence(metrics: ReviewLoadResponse) -> list[EvidenceItem]:
    period = f"{metrics.period.from_date}..{metrics.period.to_date}"
    return [
        EvidenceItem(id="ev-1", metric="gini", value=metrics.gini, period=period),
        EvidenceItem(
            id="ev-2", metric="top1_share", value=metrics.top_n_share.top1, period=period
        ),
        EvidenceItem(
            id="ev-3", metric="top3_share", value=metrics.top_n_share.top3, period=period
        ),
        EvidenceItem(
            id="ev-4", metric="total_reviews", value=metrics.totals.reviews, period=period
        ),
        EvidenceItem(
            id="ev-5", metric="total_reviewers", value=metrics.totals.reviewers, period=period
        ),
    ]


async def generate_insight(
    metrics: ReviewLoadResponse,
    session: AsyncSession,
    settings: Settings,
    metric: str = "review-load",
    cycle_time: CycleTimeResponse | None = None,
) -> InsightResponse:
    repo = metrics.repo
    from_date = metrics.period.from_date
    to_date = metrics.period.to_date
    cache_key = _cache_key(repo, from_date, to_date, metric, settings.llm_model)

    # Check cache first
    cached_row = await _load_cache(session, cache_key)
    if cached_row:
        logger.info("insight cache hit", repo=repo, cache_key=cache_key)
        data = json.loads(cached_row.response_json)
        resp = InsightResponse.model_validate(data)
        resp.cached = True
        return resp

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")

    # Build inputs
    evidence = _build_evidence(metrics)
    metrics_dict = metrics.model_dump()

    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_days = (to_dt - from_dt).days + 1

    conf_score, conf_rationale = compute_confidence(
        total_reviews=metrics.totals.reviews,
        total_prs=metrics.totals.prs,
        gini=metrics.gini,
        window_days=window_days,
    )

    # Render prompts
    sys_prompt = get_prompt(_PROMPT_NAME, "system", _PROMPT_VERSION).text
    user_tmpl = get_prompt(_PROMPT_NAME, "user", _PROMPT_VERSION)
    cycle_time_json = (
        json.dumps(cycle_time.model_dump(), indent=2) if cycle_time else "not available"
    )
    user_prompt = user_tmpl.render(
        metrics_json=json.dumps(metrics_dict, indent=2),
        cycle_time_json=cycle_time_json,
        confidence_score=conf_score,
        confidence_rationale=conf_rationale,
    )

    # First LLM attempt
    try:
        tool_output, usage = await call_llm(sys_prompt, user_prompt, settings)
    except Exception as exc:
        logger.error("llm call failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    # Grounding check
    grounding = check_grounding(tool_output, metrics_dict)
    logger.info(
        "grounding check",
        valid=grounding.valid,
        failures=grounding.failures,
        repo=repo,
    )

    if not grounding.valid:
        # Retry once with grounding failures surfaced in the prompt
        failure_desc = grounding.describe()
        logger.warning("grounding failed, retrying", failures=failure_desc)
        try:
            tool_output, usage = await call_llm(
                sys_prompt, user_prompt, settings, retry_context=failure_desc
            )
            grounding = check_grounding(tool_output, metrics_dict)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM retry failed: {exc}") from exc

        if not grounding.valid:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "grounding_failed",
                    "message": "LLM output failed grounding validation after retry",
                    "details": {"failures": grounding.failures},
                },
            )

    # Build response — use evidence from the tool output, supplemented with our pre-built set
    final_evidence = tool_output.evidence if tool_output.evidence else evidence
    response = InsightResponse(
        repo=repo,
        period={"from": from_date, "to": to_date},
        metric=metric,
        narrative=tool_output.narrative,
        hypothesis=tool_output.hypothesis,
        confidence=ConfidenceScore(score=conf_score, rationale=conf_rationale),
        evidence=final_evidence,
        model=ModelInfo(name=settings.llm_model, prompt_version=f"insights_v{_PROMPT_VERSION}"),
        cached=False,
    )

    await _store_cache(session, cache_key, repo, from_date, to_date, metric, response, settings)
    return response





async def _load_cache(session: AsyncSession, cache_key: str) -> InsightCache | None:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    result = await session.execute(
        select(InsightCache).where(
            InsightCache.cache_key == cache_key,
            InsightCache.created_at >= cutoff,
        )
    )
    return result.scalar_one_or_none()


async def _store_cache(
    session: AsyncSession,
    cache_key: str,
    repo: str,
    from_date: str,
    to_date: str,
    metric: str,
    response: InsightResponse,
    settings: Settings,
) -> None:
    response_json = response.model_dump_json()
    now = datetime.now(tz=timezone.utc)
    stmt = (
        sqlite_insert(InsightCache)
        .values(
            cache_key=cache_key,
            repo=repo,
            from_date=from_date,
            to_date=to_date,
            metric=metric,
            response_json=response_json,
            created_at=now,
            model_name=settings.llm_model,
            prompt_version=f"insights_v{_PROMPT_VERSION}",
        )
        .on_conflict_do_update(
            index_elements=["cache_key"],
            set_={"response_json": response_json, "created_at": now},
        )
    )
    await session.execute(stmt)
    await session.commit()
