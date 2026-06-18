from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.github.client import CommitData, GitHubClient, PRData
from app.ingest.coverage import compute_gaps
from app.logging_config import get_logger
from app.models.commit import Commit
from app.models.pull_request import PullRequest
from app.models.repository import Repository
from app.models.review import Review
from app.models.sync_run import SyncRun
from app.models.synced_range import SyncedRange

logger = get_logger(__name__)


class IngestService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def start_run(self, repo: str) -> SyncRun:
        """Create the repo and SyncRun records, commit, and return the run.

        Call this before returning a 202 response so the caller has a run id to poll.
        The actual ingest should then run in a background task via execute_run().
        """
        owner, name = repo.split("/", 1)
        repo_row = await self._get_or_create_repo(owner, name)
        sync_run = await self._create_sync_run(repo_row.id)
        await self._session.commit()
        return sync_run

    async def execute_run(self, run_id: int, repo: str, since: date, until: date) -> None:
        """Run the ingest for an already-created SyncRun (used from background tasks)."""
        owner, name = repo.split("/", 1)
        since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
        until_dt = datetime(until.year, until.month, until.day, 23, 59, 59, tzinfo=timezone.utc)

        result = await self._session.execute(
            select(Repository).where(Repository.owner == owner, Repository.name == name)
        )
        repo_row = result.scalar_one_or_none()
        if repo_row is None:
            raise RuntimeError(f"Repository '{repo}' not found; was start_run() called first?")

        try:
            rows = await self._run_ingest(owner, name, repo_row, since_dt, until_dt)
            await self._finish_sync_run(run_id, rows)
            # _run_ingest already commits the data rows; commit the SyncRun status update too.
            await self._session.commit()
        except Exception as exc:
            await self._fail_sync_run(run_id, str(exc))
            # Log but do not re-raise: the error is stored in the SyncRun record (status="failed")
            # and the client polls GET /sync/{id} to see it. Re-raising here causes Starlette to
            # emit a full ASGI exception traceback even though the error is already handled.
            logger.error("background sync failed", repo=repo, error=str(exc))

    async def sync(self, repo: str, since: date, until: date) -> SyncRun:
        owner, name = repo.split("/", 1)
        since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
        until_dt = datetime(until.year, until.month, until.day, 23, 59, 59, tzinfo=timezone.utc)

        repo_row = await self._get_or_create_repo(owner, name)
        sync_run = await self._create_sync_run(repo_row.id)  # type: ignore[arg-type]

        try:
            rows = await self._run_ingest(owner, name, repo_row, since_dt, until_dt)
            await self._finish_sync_run(sync_run.id, rows)  # type: ignore[arg-type]
            sync_run.status = "success"
            sync_run.rows_ingested = rows
            sync_run.finished_at = datetime.now(tz=timezone.utc)
        except Exception as exc:
            await self._fail_sync_run(sync_run.id, str(exc))  # type: ignore[arg-type]
            sync_run.status = "failed"
            sync_run.error = str(exc)
            sync_run.finished_at = datetime.now(tz=timezone.utc)
            logger.error("sync failed", repo=repo, error=str(exc))
            raise

        return sync_run

    async def _run_ingest(
        self,
        owner: str,
        name: str,
        repo_row: Repository,
        since_dt: datetime,
        until_dt: datetime,
    ) -> int:
        since = since_dt.date()
        until = until_dt.date()

        # Check what date ranges we have already stored for this repo so we only
        # call GitHub for the portions that are genuinely missing.
        result = await self._session.execute(
            select(SyncedRange).where(SyncedRange.repo_id == repo_row.id)
        )
        covered = [(r.from_date, r.to_date) for r in result.scalars().all()]
        gaps = compute_gaps(since, until, covered)

        if not gaps:
            logger.info(
                "requested range fully covered by existing data, skipping github fetch",
                repo=f"{owner}/{name}",
                since=str(since),
                until=str(until),
            )
            return 0

        logger.info(
            "fetching gaps from github",
            repo=f"{owner}/{name}",
            gaps=[(str(s), str(u)) for s, u in gaps],
        )

        total_rows = 0
        async with GitHubClient(self._settings.github_token, self._settings.github_graphql_url) as gh:
            default_branch = await gh.get_default_branch(owner, name)
            if repo_row.default_branch != default_branch:
                await self._session.execute(
                    update(Repository)
                    .where(Repository.id == repo_row.id)
                    .values(default_branch=default_branch)
                )

            for gap_since, gap_until in gaps:
                gap_since_dt = datetime(gap_since.year, gap_since.month, gap_since.day, tzinfo=timezone.utc)
                gap_until_dt = datetime(gap_until.year, gap_until.month, gap_until.day, 23, 59, 59, tzinfo=timezone.utc)

                prs = await gh.fetch_pull_requests(owner, name, gap_since_dt, gap_until_dt)
                logger.info("prs fetched", repo=f"{owner}/{name}", gap_since=str(gap_since), count=len(prs))
                rows = await self._upsert_prs(repo_row.id, prs)  # type: ignore[arg-type]

                commits = await gh.fetch_commits(owner, name, default_branch, gap_since_dt, gap_until_dt)
                logger.info("commits fetched", repo=f"{owner}/{name}", gap_since=str(gap_since), count=len(commits))
                rows += await self._upsert_commits(repo_row.id, commits)  # type: ignore[arg-type]

                # Record coverage so future syncs overlapping this range skip GitHub entirely.
                self._session.add(SyncedRange(repo_id=repo_row.id, from_date=gap_since, to_date=gap_until))  # type: ignore[arg-type]
                await self._session.commit()
                total_rows += rows

        await self._session.execute(
            update(Repository)
            .where(Repository.id == repo_row.id)
            .values(last_synced_at=datetime.now(tz=timezone.utc))
        )
        await self._session.commit()
        return total_rows

    async def _get_or_create_repo(self, owner: str, name: str) -> Repository:
        result = await self._session.execute(
            select(Repository).where(Repository.owner == owner, Repository.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        repo = Repository(owner=owner, name=name)
        self._session.add(repo)
        await self._session.flush()
        return repo

    async def _create_sync_run(self, repo_id: int) -> SyncRun:
        run = SyncRun(repo_id=repo_id, started_at=datetime.now(tz=timezone.utc))
        self._session.add(run)
        await self._session.flush()
        return run

    async def _finish_sync_run(self, run_id: int, rows: int) -> None:
        await self._session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(
                status="success",
                rows_ingested=rows,
                finished_at=datetime.now(tz=timezone.utc),
            )
        )

    async def _fail_sync_run(self, run_id: int, error: str) -> None:
        await self._session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(
                status="failed",
                error=error[:1000],
                finished_at=datetime.now(tz=timezone.utc),
            )
        )
        await self._session.commit()

    async def _upsert_prs(self, repo_id: int, prs: list[PRData]) -> int:
        if not prs:
            return 0
        rows = 0
        for pr in prs:
            stmt = (
                sqlite_insert(PullRequest)
                .values(
                    repo_id=repo_id,
                    number=pr.number,
                    author=pr.author,
                    state=pr.state,
                    created_at=pr.created_at,
                    merged_at=pr.merged_at,
                    closed_at=pr.closed_at,
                    additions=pr.additions,
                    deletions=pr.deletions,
                )
                .on_conflict_do_update(
                    index_elements=["repo_id", "number"],
                    set_={
                        "state": pr.state,
                        "merged_at": pr.merged_at,
                        "closed_at": pr.closed_at,
                        "additions": pr.additions,
                        "deletions": pr.deletions,
                    },
                )
            )
            result = await self._session.execute(stmt)
            # ON CONFLICT DO UPDATE doesn't return the row id; flush first to make the upserted
            # row visible within this transaction, then re-select to get the id for reviews.
            await self._session.flush()

            pr_result = await self._session.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == repo_id, PullRequest.number == pr.number
                )
            )
            pr_row = pr_result.scalar_one()
            rows += result.rowcount

            if pr.reviews:
                rows += await self._upsert_reviews(pr_row.id, pr.reviews, pr_row)  # type: ignore[arg-type]

        return rows

    async def _upsert_reviews(
        self, pr_id: int, reviews: list, pr_row: PullRequest
    ) -> int:
        from app.github.client import ReviewData

        rows = 0
        # SQLite stores datetimes without tzinfo; normalise to naive UTC throughout.
        first_review_at = (
            pr_row.first_review_at.replace(tzinfo=None)
            if pr_row.first_review_at and pr_row.first_review_at.tzinfo
            else pr_row.first_review_at
        )
        for rv in reviews:
            if not isinstance(rv, ReviewData):
                continue
            submitted_naive = rv.submitted_at.replace(tzinfo=None)
            stmt = (
                sqlite_insert(Review)
                .values(
                    pr_id=pr_id,
                    github_id=rv.github_id,
                    reviewer=rv.reviewer,
                    state=rv.state,
                    submitted_at=submitted_naive,
                )
                .on_conflict_do_update(
                    index_elements=["pr_id", "github_id"],
                    set_={"state": rv.state, "submitted_at": submitted_naive},
                )
            )
            result = await self._session.execute(stmt)
            rows += result.rowcount

            if first_review_at is None or submitted_naive < first_review_at:
                first_review_at = submitted_naive

        if first_review_at != pr_row.first_review_at:
            await self._session.execute(
                update(PullRequest)
                .where(PullRequest.id == pr_id)
                .values(first_review_at=first_review_at)
            )

        return rows

    async def _upsert_commits(self, repo_id: int, commits: list[CommitData]) -> int:
        if not commits:
            return 0
        rows = 0
        for c in commits:
            stmt = (
                sqlite_insert(Commit)
                .values(
                    sha=c.sha,
                    repo_id=repo_id,
                    author=c.author,
                    authored_at=c.authored_at,
                    additions=c.additions,
                    deletions=c.deletions,
                    is_on_default_branch=True,
                )
                .on_conflict_do_update(
                    index_elements=["sha"],
                    set_={
                        "additions": c.additions,
                        "deletions": c.deletions,
                        "is_on_default_branch": True,
                    },
                )
            )
            result = await self._session.execute(stmt)
            rows += result.rowcount
        return rows
