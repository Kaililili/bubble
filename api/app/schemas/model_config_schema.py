"""模型配置相关 Pydantic Schema"""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

ModelType = Literal["chat", "embedding", "rerank", "websearch"]


class ModelConfigCreateRequest(BaseModel):
    """新增模型配置请求"""
    model_type: ModelType = Field(..., description="模型类型: chat / embedding / rerank / websearch")
    provider: str = Field(..., min_length=1, max_length=50, description="提供商,如 openai / deepseek / tavily")
    model_name: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1, max_length=512, description="API Key(会加密存储)")
    base_url: str | None = Field(None, max_length=255, description="留空则使用官方默认地址")
    supports_function_call: bool = Field(True, description="是否支持原生 function calling(决定 Agent 走哪条路径)")
    is_default: bool = Field(False)


class ModelConfigUpdateRequest(BaseModel):
    """更新模型配置请求(全部可选)"""
    model_type: ModelType | None = None
    provider: str | None = Field(None, min_length=1, max_length=50)
    model_name: str | None = Field(None, min_length=1, max_length=128)
    api_key: str | None = Field(None, min_length=1, max_length=512)
    base_url: str | None = Field(None, max_length=255)
    supports_function_call: bool | None = None
    is_default: bool | None = None


class ModelConfigResponse(BaseModel):
    """模型配置响应(不含 API Key)"""
    id: UUID
    model_type: str
    provider: str
    model_name: str
    base_url: str
    supports_function_call: bool
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    model_type: ModelType
    provider: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1, max_length=512)
    base_url: str | None = Field(None, max_length=255)


class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
