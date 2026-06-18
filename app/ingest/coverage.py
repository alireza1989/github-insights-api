from datetime import date, timedelta


def compute_gaps(
    since: date,
    until: date,
    covered: list[tuple[date, date]],
) -> list[tuple[date, date]]:
    """
    Return sub-ranges of [since, until] not yet covered by any interval in `covered`.

    `covered` is a list of (from_date, to_date) inclusive tuples.  The function
    sorts and merges them internally so callers don't need to pre-sort.

    Examples
    --------
    Fully covered  → []
    No coverage    → [(since, until)]
    Gap at front   → [(since, cov_start - 1day)]
    Gap at back    → [(cov_end + 1day, until)]
    """
    if not covered:
        return [(since, until)]

    intervals = sorted(covered, key=lambda x: x[0])
    gaps: list[tuple[date, date]] = []
    cursor = since

    for cov_from, cov_to in intervals:
        if cursor > until:
            break
        if cov_from > cursor:
            gaps.append((cursor, min(cov_from - timedelta(days=1), until)))
        if cov_to >= cursor:
            cursor = cov_to + timedelta(days=1)

    if cursor <= until:
        gaps.append((cursor, until))

    return gaps
