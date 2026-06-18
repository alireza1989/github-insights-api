from typing import Optional

from pydantic import BaseModel


class Period(BaseModel):
    from_date: str
    to_date: str


class ReviewerDetail(BaseModel):
    login: str
    reviews: int
    approvals: int
    changes_requested: int
    comments: int
    median_hours_to_first_review: Optional[float]
    share_of_reviews: float


class Totals(BaseModel):
    prs: int
    reviews: int
    reviewers: int


class TopNShare(BaseModel):
    top1: float
    top3: float
    top5: float


class ReviewLoadResponse(BaseModel):
    repo: str
    period: Period
    totals: Totals
    gini: float
    top_n_share: TopNShare
    reviewers: list[ReviewerDetail]


class CycleTimeStat(BaseModel):
    p50_hours: Optional[float]
    p90_hours: Optional[float]


class AuthorCycleTime(BaseModel):
    author: str
    pr_count: int
    time_to_first_review: CycleTimeStat
    time_to_merge: CycleTimeStat


class CycleTimeResponse(BaseModel):
    repo: str
    period: Period
    pr_count: int
    time_to_first_review: CycleTimeStat
    time_to_approval: CycleTimeStat
    time_to_merge: CycleTimeStat
    by_author: list[AuthorCycleTime]
