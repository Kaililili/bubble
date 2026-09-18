"""兴趣图谱 API 路由"""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..schemas.interest_schema import (
    InterestDetail,
    InterestItem,
    MentionItem,
    RecallRequest,
)
from ..services.interest_service import InterestService

router = APIRouter(prefix="/interests", tags=["interests"])


@router.get("/timeline")
async def timeline(
    category: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    items = await svc.timeline(current_user.id, category, status)
    return success(data=[InterestItem.model_validate(i).model_dump() for i in items])


@router.get("/graph")
async def graph(
    limit: int = Query(100, ge=1, le=300),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    return success(data=await svc.graph(current_user.id, limit))


@router.get("/summary")
async def summary(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    return success(data=await svc.summary(current_user.id))


@router.get("/recent")
async def recent(
    since: datetime | None = None,
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """最近新增/更新的关注实体(聊天里提示"已加入兴趣"用)"""
    svc = InterestService(session)
    return success(data=await svc.recent(current_user.id, since, limit))


@router.get("/communities")
async def communities(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """兴趣社区(主题聚类 + 摘要,Global Search 的检索单元)"""
    from ..core.agent.interest.community import list_communities

    rows = await list_communities(session, current_user.id)
    return success(
        data=[
            {
                "key": r.key,
                "name": r.name,
                "summary": r.summary,
                "members": list(r.members or []),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    )


@router.get("/entity")
async def entity_detail(
    key: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """节点详情:连接到的关注实体/关系 + 出现的原句(点击关系图节点时用)"""
    svc = InterestService(session)
    return success(data=await svc.entity_detail(current_user.id, key))


@router.post("/recall")
async def recall(
    body: RecallRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    data = await svc.recall(
        current_user.id,
        body.query,
        hops=body.hops,
        include_cooled=body.include_cooled,
        limit=body.limit,
    )
    return success(data=data)


@router.get("/{interest_id}")
async def detail(
    interest_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    data = await svc.detail(current_user.id, interest_id)
    return success(
        data=InterestDetail(
            interest=InterestItem.model_validate(data["interest"]),
            mentions=[MentionItem.model_validate(m) for m in data["mentions"]],
        ).model_dump()
    )


@router.delete("/{interest_id}")
async def delete(
    interest_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = InterestService(session)
    return success(data=await svc.delete(current_user.id, interest_id))
