from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Review(SQLModel, table=True):
    __tablename__ = "review"
    __table_args__ = (UniqueConstraint("pr_id", "github_id", name="uq_review_pr_github"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    pr_id: int = Field(foreign_key="pull_request.id", index=True)
    github_id: str
    reviewer: str = Field(index=True)
    state: str  # APPROVED | CHANGES_REQUESTED | COMMENTED | DISMISSED
    submitted_at: datetime
