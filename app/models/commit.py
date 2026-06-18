from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class Commit(SQLModel, table=True):
    __tablename__ = "commit"
    __table_args__ = (Index("ix_commit_repo_authored", "repo_id", "authored_at"),)

    sha: str = Field(primary_key=True)
    repo_id: int = Field(foreign_key="repository.id", index=True)
    author: str = Field(index=True)
    authored_at: datetime
    additions: int = 0
    deletions: int = 0
    is_on_default_branch: bool = True
