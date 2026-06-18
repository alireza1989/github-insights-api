from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_app_settings, get_session
from app.ingest.service import IngestService
from app.schemas.sync import SyncRequest, SyncResponse

router = APIRouter(tags=["sync"])


@router.post("/sync", response_model=SyncResponse, status_code=200)
async def trigger_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> SyncResponse:
    """
    Ingest pull requests, reviews, and commits for a repository over a date range.

    The operation is idempotent — repeating the same request safely updates existing rows.
    """
    if not settings.github_token:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN is not configured")

    service = IngestService(session, settings)
    run = await service.sync(body.repo, body.since, body.until)

    return SyncResponse(
        id=run.id,  # type: ignore[arg-type]
        repo=body.repo,
        status=run.status,
        rows_ingested=run.rows_ingested,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )
