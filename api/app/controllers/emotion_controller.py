"""情绪助手 API 路由"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..schemas.emotion_schema import EmotionItem, HistoryPoint
from ..services.emotion_service import EmotionService

router = APIRouter(prefix="/emotions", tags=["emotions"])


@router.get("/history")
async def history(
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    items = await svc.history(current_user.id, granularity, days)
    return success(data=[HistoryPoint(**i).model_dump() for i in items])


@router.get("/summary")
async def summary(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    return success(data=await svc.summary(current_user.id, days))


@router.get("/profile")
async def profile(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    return success(data=await svc.profile(current_user.id, days))


@router.get("/wordcloud")
async def wordcloud(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    return success(data=await svc.wordcloud(current_user.id, days))


@router.get("/events")
async def events(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    items = await svc.events(current_user.id, limit)
    return success(data=[EmotionItem.model_validate(i).model_dump() for i in items])


@router.delete("/{snapshot_id}")
async def delete(
    snapshot_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    svc = EmotionService(session)
    await svc.delete(current_user.id, snapshot_id)
    return success(data=None)
