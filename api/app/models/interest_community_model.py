"""兴趣社区:对用户实体图做社区聚类后的摘要(Global Search 的检索单元)"""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .memory_model import EMBEDDING_DIM


class InterestCommunity(Base):
    __tablename__ = "interest_communities"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_interest_community_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    members: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
