"""工具审批单 ORM 模型 —— MCP 敏感工具(下单/写操作)的用户确认环节。

LLM 调用敏感工具时不直接执行,而是生成一条 pending 审批单;
用户在界面点「确认执行」后,后端按审批单里保存的参数真正调用 MCP tools/call。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

# 状态
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"  # 已确认,执行中
APPROVAL_EXECUTED = "executed"
APPROVAL_REJECTED = "rejected"
APPROVAL_FAILED = "failed"
APPROVAL_EXPIRED = "expired"


class ToolApproval(Base):
    __tablename__ = "tool_approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 原始工具名(执行时用) 与 给前端展示的清洗名(server__tool)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 调用参数:执行以此为准(前端不可篡改)
    args: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=APPROVAL_PENDING, index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(), onupdate=lambda: datetime.now()
    )

    def __repr__(self) -> str:
        return f"<ToolApproval {self.display_name} {self.status}>"
