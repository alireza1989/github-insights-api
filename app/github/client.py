from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.github.queries import COMMITS_ON_DEFAULT_BRANCH, DEFAULT_BRANCH_QUERY, PR_WITH_REVIEWS
from app.logging_config import get_logger

logger = get_logger(__name__)


class GitHubError(Exception):
    """Raised when the GitHub API returns an error response."""


@dataclass
class PRData:
    number: int
    state: str
    author: str
    created_at: datetime
    merged_at: Optional[datetime]
    closed_at: Optional[datetime]
    additions: int
    deletions: int
    reviews: list[ReviewData] = field(default_factory=list)


@dataclass
class ReviewData:
    github_id: str
    reviewer: str
    state: str
    submitted_at: datetime


@dataclass
class CommitData:
    sha: str
    author: str
    authored_at: datetime
    additions: int
    deletions: int


class GitHubClient:
    def __init__(self, token: str, graphql_url: str = "https://api.github.com/graphql") -> None:
        self._token = token
        self._graphql_url = graphql_url
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GitHubClient":
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-Github-Next-Global-ID": "1",
            },
            timeout=60.0,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None, "Use as async context manager"
        response = await self._client.post(
            self._graphql_url,
            json={"query": query, "variables": variables},
        )
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "60"))
            logger.warning("rate limited", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            response = await self._client.post(
                self._graphql_url,
                json={"query": query, "variables": variables},
            )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        if "errors" in body:
            raise GitHubError(f"GraphQL errors: {body['errors']}")
        return body["data"]

    async def fetch_pull_requests(
        self,
        owner: str,
        name: str,
        since: datetime,
        until: datetime,
    ) -> list[PRData]:
        prs: list[PRData] = []
        cursor: Optional[str] = None

        while True:
            data = await self._graphql(
                PR_WITH_REVIEWS,
                {"owner": owner, "name": name, "after": cursor},
            )
            page = data["repository"]["pullRequests"]
            rate = data.get("rateLimit", {})
            logger.debug("github page fetched", remaining=rate.get("remaining"), cursor=cursor)

            for node in page["nodes"]:
                created_at = _parse_dt(node["createdAt"])
                if created_at < since:
                    # GitHub returns PRs in DESC created_at order, so once we see one
                    # older than `since` every subsequent page will be older too.
                    return prs

                if created_at > until:
                    continue  # too recent; skip but keep paginating

                author_node = node.get("author")
                author = author_node["login"] if author_node else "ghost"

                reviews = []
                if node["reviews"]["pageInfo"]["hasNextPage"]:
                    logger.warning(
                        "review page truncated at 100; some reviews will be missing",
                        repo=f"{owner}/{name}",
                        pr=node["number"],
                    )
                for rv in node["reviews"]["nodes"]:
                    rv_author = rv.get("author")
                    if not rv_author or not rv.get("submittedAt"):
                        continue
                    reviews.append(
                        ReviewData(
                            github_id=str(rv["databaseId"]),
                            reviewer=rv_author["login"],
                            state=rv["state"],
                            submitted_at=_parse_dt(rv["submittedAt"]),
                        )
                    )

                prs.append(
                    PRData(
                        number=node["number"],
                        state=node["state"],
                        author=author,
                        created_at=created_at,
                        merged_at=_parse_dt(node["mergedAt"]) if node.get("mergedAt") else None,
                        closed_at=_parse_dt(node["closedAt"]) if node.get("closedAt") else None,
                        additions=node["additions"],
                        deletions=node["deletions"],
                        reviews=reviews,
                    )
                )

            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]

        return prs

    async def fetch_commits(
        self,
        owner: str,
        name: str,
        branch: str,
        since: datetime,
        until: datetime,
    ) -> list[CommitData]:
        commits: list[CommitData] = []
        cursor: Optional[str] = None

        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        until_str = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        while True:
            data = await self._graphql(
                COMMITS_ON_DEFAULT_BRANCH,
                {
                    "owner": owner,
                    "name": name,
                    "branch": branch,
                    "since": since_str,
                    "until": until_str,
                    "after": cursor,
                },
            )
            ref = data["repository"].get("ref")
            if not ref:
                break
            history = ref["target"]["history"]

            for node in history["nodes"]:
                author_node = node.get("author", {})
                user = author_node.get("user")
                login = user["login"] if user else author_node.get("name", "unknown")
                commits.append(
                    CommitData(
                        sha=node["oid"],
                        author=login,
                        authored_at=_parse_dt(node["committedDate"]),
                        additions=node["additions"],
                        deletions=node["deletions"],
                    )
                )

            if not history["pageInfo"]["hasNextPage"]:
                break
            cursor = history["pageInfo"]["endCursor"]

        return commits

    async def get_default_branch(self, owner: str, name: str) -> str:
        # Dedicated lightweight query — avoids fetching 100 PRs just to read one field.
        data = await self._graphql(DEFAULT_BRANCH_QUERY, {"owner": owner, "name": name})
        ref = data["repository"].get("defaultBranchRef")
        return ref["name"] if ref else "main"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
