"""工具管理相关 Pydantic Schema"""
from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    """工具信息"""
    key: str
    name: str
    description: str
    enabled: bool
    needs_config: bool
    configured: bool
    default_enabled: bool


class ToolUpdateRequest(BaseModel):
    """工具启停请求"""
    enabled: bool
