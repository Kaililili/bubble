"""记忆相关任务:会话滚动摘要 / 洞察刷新 / 批量洞察。"""
import logging

from celery import shared_task

from .runtime import run_async

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="memory.summarize", max_retries=3, default_retry_delay=30)
def summarize_conversation_task(self, conversation_id: str) -> dict:
    """会话摘要(未达阈值时内部直接返回,不产生模型调用)。"""
    from ..core.agent.memory.summarizer import summarize_conversation
    from ..db.postgres import async_session

    async def run():
        async with async_session() as session:
            summary = await summarize_conversation(session, conversation_id)
            return {"summarized": bool(summary)}

    try:
        return run_async(run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


@shared_task(bind=True, name="memory.refresh_insight", max_retries=3, default_retry_delay=30)
def refresh_insight_task(self, user_id: str) -> int:
    """单用户洞察刷新(内部有"新增够多 + 冷却期"节流)。"""
    from ..core.agent.memory.insight import refresh_insights
    from ..db.postgres import async_session

    async def run():
        async with async_session() as session:
            return await refresh_insights(session, user_id)

    try:
        return run_async(run())
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


@shared_task(name="memory.refresh_all_insights")
def refresh_all_insights() -> dict:
    """定时任务:对有近期活动的用户逐个刷新洞察(用户级节流仍在 refresh_insights 内)。"""
    from ..db.postgres import async_session

    async def run():
        from ..core.agent.memory.insight import refresh_insights

        from sqlalchemy import select

        from ..models.interest_model import InterestNode
        from ..models.memory_model import Memory

        done = 0
        async with async_session() as session:
            # 遍历有记忆或有兴趣的用户(没有数据的用户无需归纳)
            ids = set(
                (await session.execute(select(Memory.user_id).distinct().limit(300)))
                .scalars()
                .all()
            ) | set(
                (await session.execute(select(InterestNode.user_id).distinct().limit(300)))
                .scalars()
                .all()
            )
            for user_id in ids:
                try:
                    if await refresh_insights(session, user_id):
                        done += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("insight refresh failed for %s: %s", user_id, exc)
        return {"users": len(ids), "refreshed": done}

    return run_async(run())
