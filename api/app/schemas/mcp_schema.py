"""MCP server 配置相关 Pydantic Schema"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MCPServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="服务名(工具名前缀)")
    transport: str = Field("streamable_http", description="sse / streamable_http")
    url: str = Field(..., min_length=1, max_length=512, description="MCP 端点地址")
    token: str = Field("", max_length=1024, description="Bearer token(加密存储)")
    allowed_tools: list[str] | None = Field(
        None, description="暴露白名单;null=默认安全策略(只放行查询类)"
    )


class MCPServerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    transport: str | None = None
    url: str | None = Field(None, min_length=1, max_length=512)
    token: str | None = Field(None, max_length=1024, description="留空=保留原值")
    enabled: bool | None = Field(None, description="None=不修改")
    allowed_tools: list[str] | None = Field(
        None, description="None=不修改;[]=不暴露任何工具;列表=精确白名单"
    )
    sensitive_tools: list[str] | None = Field(
        None, description="None=不修改;列表=需用户确认才能执行的工具名"
    )


class MCPServerResponse(BaseModel):
    id: UUID
    name: str
    transport: str
    url: str
    token_masked: str = ""
    enabled: bool
    allowed_tools: list | None
    status: str
    last_error: str | None
    tools_cache: list | None
    synced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestResult(BaseModel):
    count: int
    tools: list[dict]


class CompareRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100, description="饮品关键词,如 生椰拿铁")
    longitude: float | None = Field(None, description="经度,缺省用默认位置")
    latitude: float | None = Field(None, description="纬度,缺省用默认位置")


class CompareItem(BaseModel):
    dept_id: int | None = None
    shop: str
    distance_km: float | None = None
    price: float | None = None
    product: str | None = None
    product_id: int | None = None
    address: str | None = None
    status: str | None = None
    hours: str | None = None


class CompareResult(BaseModel):
    keyword: str
    items: list[CompareItem]


class OrderPreviewRequest(BaseModel):
    dept_id: int = Field(..., description="门店 ID(比价结果返回)")
    product_id: int = Field(..., description="商品 ID(比价结果返回)")
    amount: int = Field(1, ge=1, le=20, description="数量")
    specs: list[dict] | None = Field(
        None, description="口味选择:[{attribute_id, sub_attribute_id}]"
    )


class OrderCreateRequest(BaseModel):
    dept_id: int = Field(..., description="门店 ID")
    product_id: int = Field(..., description="商品 ID")
    amount: int = Field(1, ge=1, le=20, description="数量")
    sku_code: str | None = Field(None, description="预览确认后的最终 sku(口味定稿)")
    remark: str = Field("", max_length=200, description="订单备注")


class OrderCancelRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=64, description="订单号")


class ToolApprovalResponse(BaseModel):
    id: UUID
    tool: str
    args: dict | None = None
    status: str
    result: str | None = None
    error: str | None = None
    created_at: datetime


class ApproveRequest(BaseModel):
    remember: bool = Field(
        False, description="批准后是否永久免确认(把该工具从 sensitive_tools 移除)"
    )
