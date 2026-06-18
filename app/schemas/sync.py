import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")


class SyncRequest(BaseModel):
    repo: str
    since: date
    until: date

    @field_validator("repo")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        if not _REPO_RE.match(v):
            raise ValueError("repo must be in 'owner/name' format")
        return v

    @field_validator("until")
    @classmethod
    def until_after_since(cls, v: date, info: object) -> date:
        since = getattr(info, "data", {}).get("since")
        if since and v < since:
            raise ValueError("'until' must be on or after 'since'")
        return v


class SyncResponse(BaseModel):
    id: int
    repo: str
    status: str
    rows_ingested: int
    started_at: datetime
    finished_at: Optional[datetime]
    error: Optional[str]
