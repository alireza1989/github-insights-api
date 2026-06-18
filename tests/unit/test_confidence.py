"""Unit tests for the deterministic confidence scorer."""

import pytest

from app.insights.confidence import (
    compute_confidence,
    score_effect_size,
    score_freshness,
    score_sample_size,
    score_window_length,
)


class TestSubScores:
    def test_sample_size_zero_returns_zero(self):
        assert score_sample_size(0) == 0.0

    def test_sample_size_large_saturates_at_one(self):
        assert score_sample_size(10_000) == 1.0

    def test_sample_size_500_near_one(self):
        assert score_sample_size(500) > 0.9

    def test_effect_size_neutral_gini_returns_zero(self):
        assert score_effect_size(0.5) == 0.0

    def test_effect_size_extreme_returns_one(self):
        assert score_effect_size(0.0) == 1.0
        assert score_effect_size(1.0) == 1.0

    def test_window_90_days_returns_one(self):
        assert score_window_length(90) == 1.0

    def test_window_less_than_90_scales(self):
        assert score_window_length(45) == pytest.approx(0.5)

    def test_freshness_zero_prs_returns_zero(self):
        assert score_freshness(0) == 0.0


class TestComputeConfidence:
    def test_returns_tuple(self):
        score, rationale = compute_confidence(100, 30, 0.65, 90)
        assert isinstance(score, float)
        assert isinstance(rationale, str)

    def test_score_in_range(self):
        score, _ = compute_confidence(200, 50, 0.70, 90)
        assert 0.0 <= score <= 1.0

    def test_high_data_high_score(self):
        score, rationale = compute_confidence(500, 100, 0.75, 180)
        assert score > 0.6
        assert "adequate" in rationale

    def test_low_data_low_score(self):
        score, rationale = compute_confidence(5, 2, 0.51, 7)
        assert score < 0.4
        assert "very small" in rationale

    def test_rationale_mentions_window(self):
        _, rationale = compute_confidence(100, 20, 0.6, 7)
        assert "very short" in rationale

    def test_rationale_mentions_signal(self):
        _, rationale = compute_confidence(100, 20, 0.8, 90)
        assert "strong" in rationale
