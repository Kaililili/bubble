"""瑞幸下单链路的服务端状态:预览记录 + 下单请求幂等。

这是「预览 → 确认 → 下单」闭环的持久化层:
 - LuckinOrderPreview:预览后定稿的规格/价格(下单只吃这里存的参数,不让前端传价格);
 - LuckinOrderRequest:按 request_id 去重,防止重复点击/超时重试造成重复下单。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

# 下单请求状态
ORDER_REQUEST_PENDING = "pending"
ORDER_REQUEST_CREATED = "created"
ORDER_REQUEST_UNKNOWN = "unknown"
ORDER_REQUEST_FAILED = "failed"


class LuckinOrderPreview(Base):
    """预览定稿(服务端保存参数与价格):create 只认 preview_id,防前端篡改/过期。"""

    __tablename__ = "luckin_order_previews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dept_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=1)
    sku_code: Mapped[str] = mapped_column(String(128), nullable=False)
    specs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    shop: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product: Mapped[str] = mapped_column(String(200), default="")
    spec: Mapped[str] = mapped_column(String(200), default="")
    original_price: Mapped[float | None] = mapped_column(nullable=True)
    discount_price: Mapped[float | None] = mapped_column(nullable=True)
    privilege_money: Mapped[float | None] = mapped_column(nullable=True)
    about_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.utcnow()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LuckinOrderRequest(Base):
    """下单请求幂等:同一 request_id 只允许一个执行者/一条结果。"""

    __tablename__ = "luckin_order_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_luckin_order_request"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ORDER_REQUEST_PENDING, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sku_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.utcnow()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )
