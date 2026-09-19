"""个人回顾业务入口:REST 调用直接跑 Plan-Execute 图。"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class ReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, user_id: UUID, *, days: int = 7, persist: bool = False) -> dict:
        from ..core.agent.plan import run_review

        return await run_review(self.session, user_id, days=days, persist=persist)
