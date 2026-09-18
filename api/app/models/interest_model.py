"""兴趣图谱 ORM 模型:用户关注的实体(物化索引,含向量/时间线) + 提及记录

语义:图里只有 Entity 与实体间关系,"兴趣" = (User)-[:INTERESTED_IN]->(Entity) 这条边;
本表是它的物化索引(面板/向量检索/统计直接读,不必每次跳图)。
两处存储用 (user_id, key) 关联:同一用户内 key 唯一,Neo4j 节点不需要再存 UUID。
"""
import uuid
from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .memory_model import EMBEDDING_DIM


class InterestNode(Base):
    """兴趣节点:key 归一化后唯一,时间线与统计直接查本表(不依赖 Neo4j)"""

    __tablename__ = "interest_nodes"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_interest_node_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="其他")
    # 实体类型:sport/league/team/person/org/work/product/place/tech/event/topic/other
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # active / cooled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    since: Mapped[date | None] = mapped_column(Date, nullable=True)
    until: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 最近一次成功写入 Neo4j 的时间(null = 待补偿重建)
    graph_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<InterestNode {self.key} ({self.category})>"


class InterestMention(Base):
    """兴趣提及记录:时间线证据与详情页原句来源"""

    __tablename__ = "interest_mentions"
    __table_args__ = (
        Index("ix_interest_mention_user_interest", "user_id", "interest_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    interest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interest_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    since: Mapped[date | None] = mapped_column(Date, nullable=True)
    until: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
