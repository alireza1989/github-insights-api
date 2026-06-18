from datetime import date

import pytest

from app.ingest.coverage import compute_gaps

D = date.fromisoformat


def test_no_coverage_returns_full_range():
    assert compute_gaps(D("2026-01-01"), D("2026-03-31"), []) == [
        (D("2026-01-01"), D("2026-03-31"))
    ]


def test_fully_covered_returns_empty():
    covered = [(D("2026-01-01"), D("2026-03-31"))]
    assert compute_gaps(D("2026-01-01"), D("2026-03-31"), covered) == []


def test_gap_at_the_front():
    covered = [(D("2026-02-01"), D("2026-03-31"))]
    assert compute_gaps(D("2026-01-01"), D("2026-03-31"), covered) == [
        (D("2026-01-01"), D("2026-01-31"))
    ]


def test_gap_at_the_back():
    covered = [(D("2026-01-01"), D("2026-02-28"))]
    assert compute_gaps(D("2026-01-01"), D("2026-03-31"), covered) == [
        (D("2026-03-01"), D("2026-03-31"))
    ]


def test_gap_in_the_middle():
    covered = [
        (D("2026-01-01"), D("2026-01-31")),
        (D("2026-03-01"), D("2026-03-31")),
    ]
    assert compute_gaps(D("2026-01-01"), D("2026-03-31"), covered) == [
        (D("2026-02-01"), D("2026-02-28"))
    ]


def test_extension_adds_only_new_tail():
    # Already have Jan–May; extending to Jun should return only Jun.
    covered = [(D("2026-01-01"), D("2026-05-31"))]
    assert compute_gaps(D("2026-01-01"), D("2026-06-30"), covered) == [
        (D("2026-06-01"), D("2026-06-30"))
    ]


def test_multiple_gaps():
    covered = [(D("2026-02-01"), D("2026-02-28"))]
    result = compute_gaps(D("2026-01-01"), D("2026-04-30"), covered)
    assert result == [
        (D("2026-01-01"), D("2026-01-31")),
        (D("2026-03-01"), D("2026-04-30")),
    ]


def test_unsorted_covered_is_handled():
    # Caller passes unsorted intervals; function must sort internally.
    covered = [
        (D("2026-03-01"), D("2026-03-31")),
        (D("2026-01-01"), D("2026-01-31")),
    ]
    result = compute_gaps(D("2026-01-01"), D("2026-03-31"), covered)
    assert result == [(D("2026-02-01"), D("2026-02-28"))]


def test_coverage_wider_than_requested():
    # Stored range is broader than the request — should be fully covered.
    covered = [(D("2025-01-01"), D("2026-12-31"))]
    assert compute_gaps(D("2026-01-01"), D("2026-06-30"), covered) == []
