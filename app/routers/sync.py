from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_app_settings, get_session
from app.ingest.service import IngestService
from app.models.repository import Repository
from app.models.sync_run import SyncRun
from app.schemas.sync import SyncRequest, SyncResponse

router = APIRouter(tags=["sync"])


@router.post("/sync", response_model=SyncResponse, status_code=202)
async def trigger_sync(
    body: SyncRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> SyncResponse:
    """
    Ingest pull requests, reviews, and commits for a repository over a date range.

    Returns 202 immediately with status="running" and a run id.
    Poll GET /sync/{id} to track progress. The operation is idempotent.
    """
    if not settings.github_token:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN is not configured")

    service = IngestService(session, settings)
    sync_run = await service.start_run(body.repo)

    background_tasks.add_task(
        _background_ingest,
        request.app.state.session_factory,
        settings,
        sync_run.id,
        body.repo,
        body.since,
        body.until,
    )

    return SyncResponse(
        id=sync_run.id,
        repo=body.repo,
        status="running",
        rows_ingested=0,
        started_at=sync_run.started_at,
        finished_at=None,
        error=None,
    )


async def _background_ingest(
    session_factory: object,
    settings: Settings,
    run_id: int,
    repo: str,
    since: date,
    until: date,
) -> None:
    """Run the full ingest in a background task with its own DB session."""
    async with session_factory() as session:  # type: ignore[attr-defined]
        service = IngestService(session, settings)
        await service.execute_run(run_id, repo, since, until)


@router.get("/sync/{run_id}", response_model=SyncResponse)
async def get_sync_status(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> SyncResponse:
    """Poll the status of an ingest job by its run id."""
    result = await session.execute(select(SyncRun).where(SyncRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Sync run {run_id} not found")

    repo_result = await session.execute(
        select(Repository).where(Repository.id == run.repo_id)
    )
    repo_row = repo_result.scalar_one()

    return SyncResponse(
        id=run.id,
        repo=f"{repo_row.owner}/{repo_row.name}",
        status=run.status,
        rows_ingested=run.rows_ingested,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )
