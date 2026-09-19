"""个人回顾(Plan-Execute)API:直接触发一次多步任务"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..services.review_service import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


class RunReviewRequest(BaseModel):
    days: int = Field(7, ge=1, le=30, description="回顾窗口天数")
    persist: bool = Field(False, description="是否把结果存成一条记忆")


@router.post("/run")
async def run_review(
    body: RunReviewRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """跑一次个人回顾,返回执行计划、逐步轨迹、报告与数据缺口"""
    svc = ReviewService(session)
    return success(data=await svc.run(current_user.id, days=body.days, persist=body.persist))
