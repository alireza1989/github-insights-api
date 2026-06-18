from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session
from app.metrics.cycle_time import compute_cycle_time
from app.metrics.review_load import compute_review_load
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review import Review
from app.schemas.metrics import CycleTimeResponse, ReviewLoadResponse

router = APIRouter(tags=["metrics"])


async def _get_repo(session: AsyncSession, repo: str) -> Repository:
    owner, name = repo.split("/", 1)
    result = await session.execute(
        select(Repository).where(Repository.owner == owner, Repository.name == name)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Repository '{repo}' not found. Run POST /sync first.",
        )
    return row


@router.get("/review-load", response_model=ReviewLoadResponse)
async def review_load(
    repo: str = Query(..., description="Repository in owner/name format"),
    from_date: date = Query(..., alias="from", description="Start date (inclusive)"),
    to_date: date = Query(..., alias="to", description="End date (inclusive)"),
    top: int = Query(10, ge=1, le=50, description="Number of top reviewers to return"),
    session: AsyncSession = Depends(get_session),
) -> ReviewLoadResponse:
    """Reviewer-load distribution with Gini coefficient and per-reviewer breakdown."""
    repo_row = await _get_repo(session, repo)

    from_dt = date(from_date.year, from_date.month, from_date.day)
    to_dt = date(to_date.year, to_date.month, to_date.day)

    prs_result = await session.execute(
        select(PullRequest).where(
            PullRequest.repo_id == repo_row.id,
            PullRequest.created_at >= from_dt.isoformat(),
            PullRequest.created_at <= to_dt.isoformat() + "T23:59:59",
        )
    )
    prs = list(prs_result.scalars().all())

    if not prs:
        raise HTTPException(
            status_code=404,
            detail=f"No PRs found for '{repo}' in [{from_date}, {to_date}]. Run POST /sync first.",
        )

    pr_ids = [pr.id for pr in prs if pr.id is not None]
    reviews_result = await session.execute(
        select(Review).where(Review.pr_id.in_(pr_ids))  # type: ignore[attr-defined]
    )
    reviews = list(reviews_result.scalars().all())

    return compute_review_load(prs, reviews, repo, str(from_date), str(to_date), top_n=top)


@router.get("/cycle-time", response_model=CycleTimeResponse)
async def cycle_time(
    repo: str = Query(..., description="Repository in owner/name format"),
    from_date: date = Query(..., alias="from", description="Start date (inclusive)"),
    to_date: date = Query(..., alias="to", description="End date (inclusive)"),
    session: AsyncSession = Depends(get_session),
) -> CycleTimeResponse:
    """PR cycle-time: p50/p90 for time-to-first-review, approval, and merge."""
    repo_row = await _get_repo(session, repo)

    prs_result = await session.execute(
        select(PullRequest).where(
            PullRequest.repo_id == repo_row.id,
            PullRequest.created_at >= from_date.isoformat(),
            PullRequest.created_at <= to_date.isoformat() + "T23:59:59",
        )
    )
    prs = list(prs_result.scalars().all())

    if not prs:
        raise HTTPException(
            status_code=404,
            detail=f"No PRs found for '{repo}' in [{from_date}, {to_date}]. Run POST /sync first.",
        )

    return compute_cycle_time(prs, repo, str(from_date), str(to_date))
