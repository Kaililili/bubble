"""会话与消息相关 Pydantic Schema"""
from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    """创建会话请求"""
    title: str | None = Field(None, max_length=200)


class ConversationResponse(BaseModel):
    """会话响应"""
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """消息响应"""
    id: UUID
    role: str
    content: str
    tool_calls: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    """发送聊天消息请求"""
    content: str = Field(..., min_length=1, max_length=8000)
