"""记忆 ORM 模型:用户背景(常驻) + 长尾记忆(按需)"""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

# embedding 维度,对应 BAAI/bge-m3;换模型必须保证输出维度一致
EMBEDDING_DIM = 1024


class UserProfile(Base):
    """用户背景(基本信息):key-value 结构化,每轮加载进 system prompt"""

    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_profile_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<UserProfile {self.key}: {self.value[:20]}>"


class Memory(Base):
    """长尾记忆:事实/事件/待办向量化,凭证类加密且不向量化"""

    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # credential / fact / event / todo
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="fact", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    content_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=0)
    # 使用反馈:命中次数与最近命中时间,用于检索融合排序与后续分层巩固
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    # 事实时效:active / superseded(被更新版本取代,保留可追溯)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Memory {self.type}: {self.content[:20]}>"
