"""记忆与用户背景 API 路由"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..core.security import split_credential_display
from ..db import get_session
from ..models.user_model import User
from ..schemas.memory_schema import (
    CredentialUpsertRequest,
    MemoryResponse,
    ProfileResponse,
    ProfileUpsertRequest,
    RevealResponse,
)
from ..services.memory_service import MemoryService

router = APIRouter(tags=["memory"])


@router.get("/profile")
async def list_profiles(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    items = await svc.list_profiles(current_user.id)
    return success(data=[ProfileResponse.model_validate(i).model_dump() for i in items])


@router.put("/profile")
async def upsert_profile(
    body: ProfileUpsertRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    item = await svc.upsert_profile(current_user.id, body.key, body.value, body.importance)
    return success(data=ProfileResponse.model_validate(item).model_dump())


@router.delete("/profile/{profile_id}")
async def delete_profile(
    profile_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    await svc.delete_profile(current_user.id, profile_id)
    return success(data=None)


@router.put("/memories/credential")
async def upsert_credential(
    body: CredentialUpsertRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    result = await svc.upsert_credential(current_user.id, body.key, body.value)
    return success(data={"message": result})


@router.get("/memories")
async def list_memories(
    type: str | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    items = await svc.list_memories(current_user.id, type, keyword)
    out = []
    for i in items:
        d = MemoryResponse.model_validate(i).model_dump()
        if i.type == "credential":
            d["credential_key"], d["credential_value"] = split_credential_display(i.content or "")
        out.append(d)
    return success(data=out)


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    await svc.delete_memory(current_user.id, memory_id)
    return success(data=None)


@router.post("/memories/{memory_id}/reveal")
async def reveal_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = MemoryService(session)
    content = await svc.reveal_memory(current_user.id, memory_id)
    return success(data=RevealResponse(content=content).model_dump())
