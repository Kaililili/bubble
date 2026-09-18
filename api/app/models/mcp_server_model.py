"""MCP server 配置 ORM 模型 —— 用户接入的外部 MCP 服务(如瑞幸官方 MCP)。

每个 server 是一组远程工具的来源(Streamable HTTP / SSE 传输)。
认证信息(Bearer token)用 Fernet 加密存 token_encrypted;接口返回掩码。
工具清单同步后缓存在 tools_cache;暴露白名单 allowed_tools 控制哪些工具
可进入 Agent(默认安全策略只放行查询类,防副作用工具被 LLM 误触发)。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

# 传输类型
TRANSPORT_SSE = "sse"
TRANSPORT_STREAMABLE_HTTP = "streamable_http"

# 连接状态
STATUS_UNKNOWN = "unknown"
STATUS_OK = "ok"
STATUS_ERROR = "error"


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), default=TRANSPORT_STREAMABLE_HTTP)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    token_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 暴露白名单:工具名列表;null=默认安全策略(只放行查询类),空数组=不暴露任何工具
    allowed_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 敏感工具(需用户确认后才能执行):工具名列表;null=按默认规则判定
    sensitive_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_UNKNOWN)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 同步下来的工具清单:[{"name", "description"}]
    tools_cache: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(), onupdate=lambda: datetime.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_mcp_user_name"),)

    def __repr__(self) -> str:
        return f"<MCPServer {self.name} ({self.status})>"
