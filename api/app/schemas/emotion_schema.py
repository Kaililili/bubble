"""情绪助手相关 Pydantic Schema"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EmotionItem(BaseModel):
    id: UUID
    emotion_type: str
    intensity: float
    valence: float
    arousal: float
    keywords: list = []
    trigger: str | None = None
    summary: str | None = None
    evidence: str = ""
    source: str = "llm"
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryPoint(BaseModel):
    bucket: str
    avg_valence: float
    avg_arousal: float
    count: int
    dominant_emotion: str


class DistributionItem(BaseModel):
    emotion_type: str
    count: int
    polarity: float


class WordcloudItem(BaseModel):
    word: str
    count: int
    valence: float


class ProfileResponse(BaseModel):
    dominant_emotion: str
    avg_valence: float
    avg_arousal: float
    sample_count: int
    trend: str
    recent_triggers: list[str] = []
    negative_ratio: float


class TriggerItem(BaseModel):
    trigger: str
    count: int


class SummaryResponse(BaseModel):
    days: int
    count: int
    avg_valence: float
    avg_arousal: float
    dominant_emotion: str
    trend: str
    negative_ratio: float
    distribution: list[DistributionItem] = []
    top_triggers: list[TriggerItem] = []
