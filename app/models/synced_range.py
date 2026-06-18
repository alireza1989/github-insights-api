from datetime import date
from typing import Optional

from sqlmodel import Field, SQLModel


class SyncedRange(SQLModel, table=True):
    __tablename__ = "synced_range"

    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: int = Field(foreign_key="repository.id", index=True)
    from_date: date
    to_date: date
