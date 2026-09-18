"""Celery 任务的异步运行环境。

Celery 的任务可能落在不同的事件循环里,而 SQLAlchemy 连接池 / Neo4j 驱动 / Redis 客户端
都绑定创建它们的事件循环 —— 跨循环复用会出现 "another operation is in progress"。
所以每次任务跑完都释放这几类连接,下一次任务重新建立(任务本身是幂等的,重建无副作用)。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def run_async(coro):
    """在 Celery worker 中执行一段异步逻辑:独立事件循环 + 结束后释放连接"""
    from ..db.neo4j import neo4j_client
    from ..db.postgres import engine
    from ..db.redis import close_redis

    async def _runner():
        try:
            return await coro
        finally:
            for name, closer in (
                ("postgres", engine.dispose),
                ("neo4j", neo4j_client.close),
                ("redis", close_redis),
            ):
                try:
                    await closer()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("close %s after task failed: %s", name, exc)

    return asyncio.run(_runner())
