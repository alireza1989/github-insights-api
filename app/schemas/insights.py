from typing import Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    id: str
    metric: str
    value: float
    period: str


class Hypothesis(BaseModel):
    claim: str
    supports: list[str]


class ConfidenceScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class ModelInfo(BaseModel):
    name: str
    prompt_version: str


class InsightToolInput(BaseModel):
    """Shape of the JSON the LLM emits via the emit_insight tool."""

    narrative: str
    hypothesis: Optional[Hypothesis] = None
    confidence: ConfidenceScore
    evidence: list[EvidenceItem]


class InsightResponse(BaseModel):
    """Full API response for GET /insights."""

    repo: str
    period: dict[str, str]
    metric: str
    narrative: str
    hypothesis: Optional[Hypothesis]
    confidence: ConfidenceScore
    evidence: list[EvidenceItem]
    model: ModelInfo
    cached: bool = False
