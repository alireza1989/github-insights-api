"""Integration tests for the sync endpoint using mocked GitHub API."""

import pytest
import respx
import httpx
from httpx import AsyncClient


GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Minimal response for DEFAULT_BRANCH_QUERY (only needs defaultBranchRef)
DEFAULT_BRANCH_RESPONSE = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
        }
    }
}

# Full PR response for PR_WITH_REVIEWS — includes reviews.pageInfo since we added it
PR_RESPONSE = {
    "data": {
        "repository": {
            "defaultBranchRef": {"name": "main"},
            "pullRequests": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "number": 1,
                        "state": "MERGED",
                        "createdAt": "2024-03-15T10:00:00Z",
                        "mergedAt": "2024-03-17T14:00:00Z",
                        "closedAt": "2024-03-17T14:00:00Z",
                        "additions": 42,
                        "deletions": 8,
                        "author": {"login": "alice"},
                        "reviews": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [
                                {
                                    "databaseId": 101,
                                    "state": "APPROVED",
                                    "submittedAt": "2024-03-16T09:00:00Z",
                                    "author": {"login": "bob"},
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "rateLimit": {"remaining": 4999, "resetAt": "2024-03-15T11:00:00Z"},
    }
}

COMMIT_RESPONSE = {
    "data": {
        "repository": {
            "ref": {
                "target": {
                    "history": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "oid": "abc123",
                                "additions": 42,
                                "deletions": 8,
                                "committedDate": "2024-03-15T10:00:00Z",
                                "author": {"user": {"login": "alice"}, "name": "Alice"},
                            }
                        ],
                    }
                }
            }
        },
        "rateLimit": {"remaining": 4998, "resetAt": "2024-03-15T11:00:00Z"},
    }
}


@pytest.mark.asyncio
async def test_sync_success(async_client: AsyncClient) -> None:
    with respx.mock(base_url=GITHUB_GRAPHQL_URL) as mock:
        mock.post("").side_effect = [
            httpx.Response(200, json=DEFAULT_BRANCH_RESPONSE),  # get_default_branch
            httpx.Response(200, json=PR_RESPONSE),              # fetch_pull_requests
            httpx.Response(200, json=COMMIT_RESPONSE),          # fetch_commits
        ]

        resp = await async_client.post(
            "/sync",
            json={"repo": "owner/testrepo", "since": "2024-01-01", "until": "2024-12-31"},
        )

    # POST /sync returns 202 immediately; background task runs after response is sent
    assert resp.status_code == 202
    body = resp.json()
    run_id = body["id"]
    assert body["status"] == "running"

    # Poll the status endpoint to confirm the background task completed successfully
    status_resp = await async_client.get(f"/sync/{run_id}")
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["status"] == "success"
    assert status_body["rows_ingested"] > 0


@pytest.mark.asyncio
async def test_sync_invalid_repo_format(async_client: AsyncClient) -> None:
    resp = await async_client.post(
        "/sync",
        json={"repo": "not-a-valid-repo", "since": "2024-01-01", "until": "2024-12-31"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sync_until_before_since(async_client: AsyncClient) -> None:
    resp = await async_client.post(
        "/sync",
        json={"repo": "owner/repo", "since": "2024-06-01", "until": "2024-01-01"},
    )
    assert resp.status_code == 422
