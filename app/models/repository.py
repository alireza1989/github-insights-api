from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Repository(SQLModel, table=True):
    __tablename__ = "repository"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repository_owner_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    owner: str = Field(index=True)
    name: str = Field(index=True)
    default_branch: str = "main"
    last_synced_at: Optional[datetime] = None
