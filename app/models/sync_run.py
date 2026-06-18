from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SyncRun(SQLModel, table=True):
    __tablename__ = "sync_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: int = Field(foreign_key="repository.id", index=True)
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str = "running"  # running | success | failed
    rows_ingested: int = 0
    error: Optional[str] = None
