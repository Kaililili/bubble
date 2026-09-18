"""模型配置 API 路由"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.llm.provider import PROVIDER_DEFAULT_BASE_URL, test_connection
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..schemas.model_config_schema import (
    ModelConfigCreateRequest,
    ModelConfigResponse,
    ModelConfigUpdateRequest,
    TestConnectionRequest,
    TestConnectionResponse,
)
from ..services.model_config_service import ModelConfigService

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_models(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ModelConfigService(session)
    items = await svc.list(current_user.id)
    return success(data=[ModelConfigResponse.model_validate(i).model_dump() for i in items])


@router.post("")
async def create_model(
    body: ModelConfigCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ModelConfigService(session)
    config = await svc.create(current_user.id, body)
    return success(data=ModelConfigResponse.model_validate(config).model_dump())


@router.put("/{config_id}")
async def update_model(
    config_id: UUID,
    body: ModelConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ModelConfigService(session)
    config = await svc.update(current_user.id, config_id, body)
    return success(data=ModelConfigResponse.model_validate(config).model_dump())


@router.delete("/{config_id}")
async def delete_model(
    config_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = ModelConfigService(session)
    await svc.delete(current_user.id, config_id)
    return success(data=None)


@router.post("/test")
async def test_model(body: TestConnectionRequest):
    """测试连接(不需要登录也可以测试,前端配置时调用)"""
    base_url = (body.base_url or "").strip() or PROVIDER_DEFAULT_BASE_URL.get(body.provider, "")
    if not base_url:
        result = TestConnectionResponse(success=False, message="请填写 base_url 或选择已知 provider")
        return success(data=result.model_dump())
    ok, message = await test_connection(body.model_type, base_url, body.api_key, body.model_name)
    result = TestConnectionResponse(success=ok, message=message)
    return success(data=result.model_dump())
