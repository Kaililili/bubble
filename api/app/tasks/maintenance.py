"""定时维护任务:兴趣社区全量重聚类。"""
import logging

from celery import shared_task

from .runtime import run_async

logger = logging.getLogger(__name__)


@shared_task(name="interest.recluster_communities")
def recluster_communities() -> dict:
    """增量聚类保实时,这个全量任务保质量:每天重跑一次 LPA 并刷新社区摘要。"""
    from ..core.agent.interest.community import refresh_communities
    from ..db.postgres import async_session

    async def run():
        from sqlalchemy import select

        from ..models.interest_model import InterestNode

        done = 0
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(InterestNode.user_id).distinct().limit(200)
                )
            ).scalars().all()
            for user_id in rows:
                try:
                    await refresh_communities(session, user_id, force=True)
                    done += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("recluster failed for %s: %s", user_id, exc)
        return {"users": len(rows), "reclustered": done}

    return run_async(run())
