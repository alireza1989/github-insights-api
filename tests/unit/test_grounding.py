"""Unit tests for the grounding validators."""

import pytest

from app.insights.grounding import check_grounding
from app.schemas.insights import ConfidenceScore, EvidenceItem, Hypothesis, InsightToolInput


def make_tool_output(
    narrative: str,
    evidence: list[EvidenceItem] | None = None,
    hypothesis: Hypothesis | None = None,
) -> InsightToolInput:
    return InsightToolInput(
        narrative=narrative,
        evidence=evidence or [EvidenceItem(id="ev-1", metric="gini", value=0.61, period="2024-01..2024-06")],
        hypothesis=hypothesis,
        confidence=ConfidenceScore(score=0.72, rationale="test"),
    )


METRICS = {
    "gini": 0.61,
    "top_n_share": {"top1": 0.31, "top3": 0.62},
    "totals": {"prs": 142, "reviews": 487, "reviewers": 23},
    "reviewers": [{"login": "alice", "reviews": 152, "share_of_reviews": 0.31}],
}


class TestNumericGrounding:
    def test_valid_number_passes(self):
        output = make_tool_output("Review load Gini is 0.61 in this period.")
        result = check_grounding(output, METRICS)
        assert result.valid

    def test_invented_number_fails(self):
        output = make_tool_output("Review load Gini is 0.99 in this period.")
        result = check_grounding(output, METRICS)
        assert not result.valid
        assert any("0.99" in f for f in result.failures)

    def test_percentage_matches_decimal(self):
        output = make_tool_output("Alice handles 31% of all reviews.")
        result = check_grounding(output, METRICS)
        assert result.valid

    def test_large_count_passes(self):
        output = make_tool_output("There are 487 reviews total.")
        result = check_grounding(output, METRICS)
        assert result.valid

    def test_invented_count_fails(self):
        output = make_tool_output("There are 999 reviews total.")
        result = check_grounding(output, METRICS)
        assert not result.valid


class TestEvidenceIdIntegrity:
    def test_valid_hypothesis_reference_passes(self):
        evidence = [
            EvidenceItem(id="ev-1", metric="gini", value=0.61, period="p"),
            EvidenceItem(id="ev-2", metric="top1", value=0.31, period="p"),
        ]
        hyp = Hypothesis(claim="Concentration is increasing.", supports=["ev-1"])
        output = make_tool_output("Gini is 0.61.", evidence=evidence, hypothesis=hyp)
        result = check_grounding(output, METRICS)
        assert result.valid

    def test_missing_evidence_id_fails(self):
        evidence = [EvidenceItem(id="ev-1", metric="gini", value=0.61, period="p")]
        hyp = Hypothesis(claim="Concentration is high.", supports=["ev-99"])
        output = make_tool_output("Gini is 0.61.", evidence=evidence, hypothesis=hyp)
        result = check_grounding(output, METRICS)
        assert not result.valid
        assert any("ev-99" in f for f in result.failures)
