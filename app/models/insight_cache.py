from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class InsightCache(SQLModel, table=True):
    __tablename__ = "insight_cache"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_insight_cache_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    cache_key: str = Field(index=True)
    repo: str
    from_date: str
    to_date: str
    metric: str
    response_json: str
    created_at: datetime
    model_name: str
    prompt_version: str
