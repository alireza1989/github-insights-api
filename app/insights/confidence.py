"""
Deterministic confidence scorer.

Produces a [0, 1] score from observable data properties.
The LLM receives this score and calibrates its language accordingly
but cannot override or invent its own confidence.
"""

from __future__ import annotations

import math

# sample_size carries the highest weight — small n is the most common cause of spurious signals.
_WEIGHTS = {
    "sample_size": 0.35,
    "effect_size": 0.30,
    "window_length": 0.20,
    "data_freshness": 0.15,
}


def score_sample_size(total_reviews: int) -> float:
    """Log-scale score saturating around 500 reviews."""
    return min(1.0, math.log1p(total_reviews) / math.log1p(500))


def score_effect_size(gini: float) -> float:
    """How far the Gini coefficient is from 0.5 (neutral/uniform)."""
    return min(1.0, abs(gini - 0.5) * 4.0)


def score_window_length(window_days: int) -> float:
    """90+ days is a full quarter — the ideal window for review patterns."""
    return min(1.0, window_days / 90.0)


def score_freshness(total_prs: int) -> float:
    """Proxy for data completeness: more PRs in window = fresher picture."""
    return min(1.0, math.log1p(total_prs) / math.log1p(100))


def compute_confidence(
    total_reviews: int,
    total_prs: int,
    gini: float,
    window_days: int,
) -> tuple[float, str]:
    """Return (score, rationale) as a deterministic computation."""
    sub_scores = {
        "sample_size": score_sample_size(total_reviews),
        "effect_size": score_effect_size(gini),
        "window_length": score_window_length(window_days),
        "data_freshness": score_freshness(total_prs),
    }

    score = sum(_WEIGHTS[k] * v for k, v in sub_scores.items())
    score = round(score, 2)

    parts: list[str] = []

    if total_reviews < 30:
        parts.append(f"very small sample ({total_reviews} reviews)")
    elif total_reviews < 100:
        parts.append(f"small sample ({total_reviews} reviews)")
    else:
        parts.append(f"adequate sample ({total_reviews} reviews)")

    if abs(gini - 0.5) > 0.2:
        parts.append("strong concentration signal")
    elif abs(gini - 0.5) > 0.1:
        parts.append("moderate concentration signal")
    else:
        parts.append("weak concentration signal")

    if window_days < 14:
        parts.append("very short window")
    elif window_days < 30:
        parts.append("short window")
    elif window_days < 90:
        parts.append("moderate window")
    else:
        parts.append("full-quarter window")

    rationale = "; ".join(parts)
    return score, rationale
