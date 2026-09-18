"""情绪快照 ORM 模型:每轮对话的情绪记录(离散主情绪 + 效价/唤醒度)"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class EmotionSnapshot(Base):
    """单轮情绪记录:供情绪页曲线/分布/词云与回答时的情绪档案使用"""

    __tablename__ = "emotion_snapshots"
    __table_args__ = (Index("ix_emotion_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 受控情绪词表(喜悦/平静/期待/感动/悲伤/愤怒/恐惧/焦虑/疲惫/厌恶/惊讶/孤独/中性)
    emotion_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intensity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    valence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    arousal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    trigger: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 原句(已脱敏),用于面板回看与 grounding 追溯
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # llm / rule(规则兜底写入)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    def __repr__(self) -> str:
        return f"<EmotionSnapshot {self.emotion_type} v={self.valence} i={self.intensity}>"
