"""MCP server 配置 API 路由"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..schemas.mcp_schema import (
    CompareRequest,
    CompareResult,
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
    OrderCancelRequest,
    OrderCreateRequest,
    OrderPreviewRequest,
    TestResult,
    ToolApprovalResponse,
    ApproveRequest,
)
from ..services.mcp_service import MCPService

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _to_out(server) -> dict:
    d = MCPServerResponse.model_validate(server).model_dump()
    d["token_masked"] = "******" if server.token_encrypted else ""
    return d


@router.get("/servers")
async def list_servers(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    items = await MCPService(session).list_servers(current_user.id)
    return success(data=[_to_out(i) for i in items])


@router.post("/servers")
async def create_server(
    body: MCPServerCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    item = await MCPService(session).create_server(current_user.id, body)
    return success(data=_to_out(item))


@router.put("/servers/{server_id}")
async def update_server(
    server_id: UUID,
    body: MCPServerUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    item = await MCPService(session).update_server(current_user.id, server_id, body)
    return success(data=_to_out(item))


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await MCPService(session).delete_server(current_user.id, server_id)
    return success(data=None)


@router.post("/servers/{server_id}/test")
async def test_server(
    server_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await MCPService(session).test_server(current_user.id, server_id)
    return success(data=TestResult(**result).model_dump())


@router.get("/servers/{server_id}/tools")
async def get_server_tools(
    server_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tools = await MCPService(session).get_server_tools(current_user.id, server_id)
    return success(data=tools)


@router.post("/luckin/compare")
async def compare_luckin(
    body: CompareRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    items = await MCPService(session).compare_luckin(
        current_user.id, body.keyword, body.longitude, body.latitude
    )
    return success(
        data=CompareResult(keyword=body.keyword, items=items).model_dump()
    )


@router.post("/luckin/order/preview")
async def preview_order(
    body: OrderPreviewRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).preview_order(
        current_user.id, body.dept_id, body.product_id, body.amount, body.specs
    )
    return success(data=data)


@router.post("/luckin/order/options")
async def order_options(
    body: OrderPreviewRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).order_options(
        current_user.id, body.dept_id, body.product_id
    )
    return success(data=data)


@router.post("/luckin/order/create")
async def create_order(
    body: OrderCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).create_order(
        current_user.id,
        body.dept_id,
        body.product_id,
        body.amount,
        body.sku_code,
        body.remark,
    )
    return success(data=data)


@router.post("/luckin/order/cancel")
async def cancel_order(
    body: OrderCancelRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).cancel_order(current_user.id, body.order_id)
    return success(data=data)


@router.get("/luckin/order/{order_id}")
async def query_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).query_order(current_user.id, order_id)
    return success(data=data)


def _approval_out(a) -> dict:
    d = ToolApprovalResponse(
        id=a.id,
        tool=a.display_name,
        args=a.args,
        status=a.status,
        result=a.result,
        error=a.error,
        created_at=a.created_at,
    ).model_dump()
    return d


@router.get("/approvals")
async def list_approvals(
    status: str | None = "pending",
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    items = await MCPService(session).list_approvals(current_user.id, status)
    return success(data=[_approval_out(i) for i in items])


@router.post("/approvals/{approval_id}/approve")
async def approve_tool(
    approval_id: UUID,
    body: ApproveRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    remember = bool(body.remember) if body else False
    data = await MCPService(session).approve_tool(current_user.id, approval_id, remember)
    return success(data=data)


@router.post("/approvals/{approval_id}/reject")
async def reject_tool(
    approval_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await MCPService(session).reject_tool(current_user.id, approval_id)
    return success(data=data)
