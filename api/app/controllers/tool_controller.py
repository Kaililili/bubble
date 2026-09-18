"""工具管理 API 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..schemas.tool_schema import ToolInfo, ToolUpdateRequest
from ..services.tool_service import ToolService

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ToolService(session)
    items = await svc.list(current_user.id)
    return success(data=[ToolInfo(**i).model_dump() for i in items])


@router.put("/{tool_key}")
async def set_tool_enabled(
    tool_key: str,
    body: ToolUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ToolService(session)
    await svc.set_enabled(current_user.id, tool_key, body.enabled)
    return success(data=None)
