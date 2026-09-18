"""兴趣图谱相关 Pydantic Schema"""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InterestItem(BaseModel):
    id: UUID
    key: str
    name: str
    category: str
    status: str
    since: date | None = None
    until: date | None = None
    last_seen: datetime | None = None
    mention_count: int

    model_config = {"from_attributes": True}


class MentionItem(BaseModel):
    id: UUID
    raw_text: str
    since: date | None = None
    until: date | None = None
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


class InterestDetail(BaseModel):
    interest: InterestItem
    mentions: list[MentionItem]


class RecallRequest(BaseModel):
    query: str = ""
    hops: int = Field(2, ge=1, le=3)
    include_cooled: bool = True
    limit: int = Field(8, ge=1, le=20)
