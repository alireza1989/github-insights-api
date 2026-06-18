from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.models.pull_request import PullRequest
from app.models.review import Review
from app.schemas.metrics import Period, ReviewerDetail, ReviewLoadResponse, Totals, TopNShare


def compute_gini(values: list[float]) -> float:
    """Gini coefficient of a distribution. Returns 0 for empty or uniform input."""
    if not values or sum(values) == 0:
        return 0.0
    n = len(values)
    sorted_vals = sorted(values)
    # Closed-form Gini: rank-weighted cumulative sum avoids O(n²) pairwise comparisons.
    cumsum = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    return (2 * cumsum / (n * sum(sorted_vals))) - (n + 1) / n


def compute_review_load(
    prs: list[PullRequest],
    reviews: list[Review],
    repo: str,
    from_date: str,
    to_date: str,
    top_n: int = 10,
) -> ReviewLoadResponse:
    total_prs = len(prs)
    total_reviews = len(reviews)

    if total_reviews == 0:
        return ReviewLoadResponse(
            repo=repo,
            period=Period(from_date=from_date, to_date=to_date),
            totals=Totals(prs=total_prs, reviews=0, reviewers=0),
            gini=0.0,
            top_n_share=TopNShare(top1=0.0, top3=0.0, top5=0.0),
            avg_reviews_per_reviewer=0.0,
            reviewers=[],
        )

    # Reviews per reviewer
    reviewer_reviews: dict[str, list[Review]] = defaultdict(list)
    for rv in reviews:
        reviewer_reviews[rv.reviewer].append(rv)

    total_reviewers = len(reviewer_reviews)
    counts = Counter({r: len(rvs) for r, rvs in reviewer_reviews.items()})
    avg_reviews = total_reviews / total_reviewers

    # Gini over review counts
    gini = compute_gini(list(counts.values()))

    # Build first-review times per PR for median computation
    pr_first_review: dict[int, datetime] = {}
    for rv in reviews:
        existing = pr_first_review.get(rv.pr_id)
        if existing is None or rv.submitted_at < existing:
            pr_first_review[rv.pr_id] = rv.submitted_at

    pr_created: dict[int, datetime] = {pr.id: pr.created_at for pr in prs if pr.id is not None}

    def median_hours_to_first_review_for(reviewer: str) -> Optional[float]:
        hours: list[float] = []
        for rv in reviewer_reviews[reviewer]:
            created = pr_created.get(rv.pr_id)
            first = pr_first_review.get(rv.pr_id)
            if created and first and first == rv.submitted_at:
                delta = (first - created).total_seconds() / 3600
                if delta >= 0:
                    hours.append(delta)
        return round(statistics.median(hours), 2) if hours else None

    # Top N reviewers by review count
    top_reviewers = counts.most_common(top_n)
    reviewer_details = [
        ReviewerDetail(
            login=login,
            reviews=count,
            approvals=sum(1 for rv in reviewer_reviews[login] if rv.state == "APPROVED"),
            changes_requested=sum(
                1 for rv in reviewer_reviews[login] if rv.state == "CHANGES_REQUESTED"
            ),
            comments=sum(1 for rv in reviewer_reviews[login] if rv.state == "COMMENTED"),
            median_hours_to_first_review=median_hours_to_first_review_for(login),
            share_of_reviews=round(count / total_reviews, 4),
            relative_load=round(count / avg_reviews, 2),
        )
        for login, count in top_reviewers
    ]

    # Concentration shares
    top1 = (top_reviewers[0][1] / total_reviews) if top_reviewers else 0.0
    top3 = sum(c for _, c in top_reviewers[:3]) / total_reviews if len(top_reviewers) >= 1 else 0.0
    top5 = sum(c for _, c in top_reviewers[:5]) / total_reviews if len(top_reviewers) >= 1 else 0.0

    return ReviewLoadResponse(
        repo=repo,
        period=Period(from_date=from_date, to_date=to_date),
        totals=Totals(prs=total_prs, reviews=total_reviews, reviewers=total_reviewers),
        gini=round(gini, 4),
        top_n_share=TopNShare(top1=round(top1, 4), top3=round(top3, 4), top5=round(top5, 4)),
        avg_reviews_per_reviewer=round(avg_reviews, 2),
        reviewers=reviewer_details,
    )
