"""Unit tests for the metrics pure functions."""

from datetime import datetime, timezone

import pytest

from app.metrics.review_load import compute_gini, compute_review_load
from app.metrics.cycle_time import compute_cycle_time
from app.models.pull_request import PullRequest
from app.models.review import Review


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ── Gini coefficient ──────────────────────────────────────────────────────────

class TestGini:
    def test_empty_returns_zero(self):
        assert compute_gini([]) == 0.0

    def test_uniform_returns_zero(self):
        assert compute_gini([5.0, 5.0, 5.0]) == 0.0

    def test_monopoly_returns_near_one(self):
        # One person does everything
        result = compute_gini([0.0, 0.0, 100.0])
        assert result > 0.6

    def test_known_value(self):
        # For [1, 2, 3, 4]: Gini ≈ 0.25
        result = compute_gini([1, 2, 3, 4])
        assert 0.20 < result < 0.30

    def test_two_equal(self):
        assert compute_gini([10.0, 10.0]) == 0.0


# ── Review load ───────────────────────────────────────────────────────────────

def make_pr(id: int, author: str = "alice", created_at: str = "2024-01-10") -> PullRequest:
    return PullRequest(
        id=id,
        repo_id=1,
        number=id,
        author=author,
        state="MERGED",
        created_at=dt(created_at),
        merged_at=dt("2024-01-15"),
        additions=10,
        deletions=5,
    )


def make_review(id: int, pr_id: int, reviewer: str, state: str = "APPROVED") -> Review:
    return Review(
        id=id,
        pr_id=pr_id,
        github_id=str(id),
        reviewer=reviewer,
        state=state,
        submitted_at=dt("2024-01-11"),
    )


class TestReviewLoad:
    def test_empty_reviews_returns_zero_gini(self):
        prs = [make_pr(1)]
        result = compute_review_load(prs, [], "owner/repo", "2024-01-01", "2024-01-31")
        assert result.gini == 0.0
        assert result.totals.reviews == 0

    def test_single_reviewer_gini_near_one(self):
        prs = [make_pr(1), make_pr(2)]
        reviews = [make_review(1, 1, "alice"), make_review(2, 2, "alice")]
        result = compute_review_load(prs, reviews, "owner/repo", "2024-01-01", "2024-01-31")
        assert result.gini == 0.0  # All reviews by one person: perfectly "concentrated" but Gini=0 with n=1
        assert result.totals.reviews == 2
        assert result.reviewers[0].login == "alice"
        assert result.reviewers[0].share_of_reviews == 1.0

    def test_equal_load_low_gini(self):
        prs = [make_pr(i) for i in range(1, 5)]
        reviews = [
            make_review(1, 1, "alice"), make_review(2, 2, "bob"),
            make_review(3, 3, "carol"), make_review(4, 4, "dave"),
        ]
        result = compute_review_load(prs, reviews, "owner/repo", "2024-01-01", "2024-01-31")
        assert result.gini == 0.0
        assert result.top_n_share.top1 == 0.25

    def test_top_n_capped(self):
        prs = [make_pr(i) for i in range(1, 21)]
        reviews = [make_review(i, i, f"reviewer_{i}") for i in range(1, 21)]
        result = compute_review_load(prs, reviews, "o/r", "2024-01-01", "2024-01-31", top_n=5)
        assert len(result.reviewers) == 5

    def test_correct_share_computation(self):
        prs = [make_pr(1), make_pr(2), make_pr(3), make_pr(4)]
        reviews = [
            make_review(1, 1, "alice"), make_review(2, 2, "alice"),
            make_review(3, 3, "alice"), make_review(4, 4, "bob"),
        ]
        result = compute_review_load(prs, reviews, "o/r", "2024-01-01", "2024-01-31")
        alice = next(r for r in result.reviewers if r.login == "alice")
        assert alice.share_of_reviews == 0.75


# ── Cycle time ────────────────────────────────────────────────────────────────

class TestCycleTime:
    def test_no_merged_prs(self):
        pr = PullRequest(
            id=1, repo_id=1, number=1, author="alice", state="OPEN",
            created_at=dt("2024-01-01"), additions=0, deletions=0,
        )
        result = compute_cycle_time([pr], "o/r", "2024-01-01", "2024-01-31")
        assert result.pr_count == 0
        assert result.time_to_merge.p50_hours is None

    def test_single_merged_pr(self):
        pr = PullRequest(
            id=1, repo_id=1, number=1, author="alice", state="MERGED",
            created_at=dt("2024-01-01T00:00:00"),
            merged_at=dt("2024-01-02T12:00:00"),
            first_review_at=dt("2024-01-01T06:00:00"),
            additions=10, deletions=0,
        )
        result = compute_cycle_time([pr], "o/r", "2024-01-01", "2024-01-31")
        assert result.pr_count == 1
        assert result.time_to_first_review.p50_hours == 6.0
        assert result.time_to_merge.p50_hours == 36.0
