from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from app.models.pull_request import PullRequest
from app.schemas.metrics import (
    AuthorCycleTime,
    CycleTimeResponse,
    CycleTimeStat,
    Period,
)


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    # Nearest-rank method with ceil: ceil avoids truncation error that makes p90 return p80
    # on small lists (e.g. int(2 * 0.9) - 1 = 0 instead of the correct 1).
    idx = min(n - 1, max(0, math.ceil(pct / 100 * n) - 1))
    return round(sorted_vals[idx], 2)


def _hours(a: object, b: object) -> Optional[float]:
    if a is None or b is None:
        return None
    delta = (b - a).total_seconds() / 3600  # type: ignore[operator]
    return delta if delta >= 0 else None


def compute_cycle_time(
    prs: list[PullRequest],
    repo: str,
    from_date: str,
    to_date: str,
) -> CycleTimeResponse:
    merged = [pr for pr in prs if pr.merged_at is not None]

    ttfr_hours: list[float] = []
    ttm_hours: list[float] = []
    by_author: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"ttfr": [], "ttm": []})

    for pr in merged:
        h_ttfr = _hours(pr.created_at, pr.first_review_at)
        h_ttm = _hours(pr.created_at, pr.merged_at)

        if h_ttfr is not None:
            ttfr_hours.append(h_ttfr)
            by_author[pr.author]["ttfr"].append(h_ttfr)

        if h_ttm is not None:
            ttm_hours.append(h_ttm)
            by_author[pr.author]["ttm"].append(h_ttm)

    # time-to-approval: approximated by time-to-first-review since we track
    # first_review_at on the PR but don't store the approval state separately.
    tta_hours = ttfr_hours

    def stat(hours: list[float]) -> CycleTimeStat:
        return CycleTimeStat(p50_hours=_percentile(hours, 50), p90_hours=_percentile(hours, 90))

    author_stats = [
        AuthorCycleTime(
            author=author,
            pr_count=len(data["ttm"]) or len(data["ttfr"]),
            time_to_first_review=stat(data["ttfr"]),
            time_to_merge=stat(data["ttm"]),
        )
        for author, data in sorted(by_author.items(), key=lambda kv: -len(kv[1]["ttm"]))
    ]

    return CycleTimeResponse(
        repo=repo,
        period=Period(from_date=from_date, to_date=to_date),
        pr_count=len(merged),
        time_to_first_review=stat(ttfr_hours),
        time_to_approval=stat(tta_hours),
        time_to_merge=stat(ttm_hours),
        by_author=author_stats[:20],
    )
