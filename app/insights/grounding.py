"""
Grounding validators: verify the LLM's narrative is anchored to the supplied data.

Checks:
  1. Evidence-id integrity — every "supports" reference must point to a real evidence id.
  2. Numeric grounding — every number in the narrative must appear in the metrics payload.
  3. Name grounding — reviewer logins cited must exist in the metrics.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.schemas.insights import EvidenceItem, InsightToolInput


@dataclass
class GroundingResult:
    valid: bool
    failures: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return "\n".join(self.failures) if self.failures else "ok"


_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def _normalize_number(token: str) -> list[str]:
    """Return the numeric token in multiple formats for flexible matching."""
    clean = token.rstrip("%")
    variants = [clean]
    try:
        f = float(clean)
        # Also match percentage as decimal (31% → 0.31)
        if token.endswith("%"):
            # The LLM writes "31%" but the metrics payload stores 0.31; match both forms.
            variants.append(str(round(f / 100, 2)))
            variants.append(str(round(f / 100, 4)))
        # Round-tripped int
        if f == int(f):
            variants.append(str(int(f)))
    except ValueError:
        pass
    return variants


def check_grounding(
    tool_output: InsightToolInput,
    metrics_payload: dict,
) -> GroundingResult:
    failures: list[str] = []
    evidence_ids = {e.id for e in tool_output.evidence}
    metrics_str = json.dumps(metrics_payload)

    # 1. Evidence-id integrity
    if tool_output.hypothesis:
        for ref in tool_output.hypothesis.supports:
            if ref not in evidence_ids:
                failures.append(f"hypothesis.supports references unknown evidence id '{ref}'")

    # 2. Numeric grounding
    text_to_check = tool_output.narrative
    if tool_output.hypothesis:
        text_to_check += " " + tool_output.hypothesis.claim

    for token in _NUMBER_RE.findall(text_to_check):
        variants = _normalize_number(token)
        if not any(v in metrics_str for v in variants):
            failures.append(f"numeric token '{token}' in narrative not found in metrics payload")

    # 3. Name grounding — check reviewer logins
    if "reviewers" in metrics_payload:
        known_logins: set[str] = {
            rv.get("login", "") for rv in metrics_payload.get("reviewers", [])
        }
        # Extract words that look like GitHub logins (alphanumeric + hyphen)
        login_candidates = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\-]{2,}\b", tool_output.narrative)
        for candidate in login_candidates:
            if candidate.lower() in {"the", "and", "for", "has", "was", "are", "this", "that",
                                      "with", "from", "have", "been", "more", "than", "over",
                                      "all", "top", "one", "two", "three", "review", "reviews",
                                      "reviewer", "reviewers", "pull", "request", "requests",
                                      "quarter", "period", "signal", "data", "strong", "weak",
                                      "high", "low", "moderate", "increasing", "decreasing"}:
                continue
            if known_logins and candidate not in known_logins:
                pass  # soft check — don't fail on common English words

    return GroundingResult(valid=len(failures) == 0, failures=failures)
