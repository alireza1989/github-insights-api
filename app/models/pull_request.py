from datetime import datetime
from typing import Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel


class PullRequest(SQLModel, table=True):
    __tablename__ = "pull_request"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_pr_repo_number"),
        Index("ix_pr_repo_created", "repo_id", "created_at"),
        Index("ix_pr_repo_merged", "repo_id", "merged_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: int = Field(foreign_key="repository.id", index=True)
    number: int
    author: str = Field(index=True)
    state: str  # OPEN | CLOSED | MERGED
    created_at: datetime
    merged_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    first_review_at: Optional[datetime] = None
    additions: int = 0
    deletions: int = 0
