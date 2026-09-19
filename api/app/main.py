from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings, validate_secrets
from .controllers.router import api_router
from .controllers import health_controller
from .controllers import auth_controller
from .core.exceptions import register_exception_handlers
from .core.logging import setup_logging
from .core.request_context import RequestContextMiddleware
from .db import close_postgres, neo4j_client, close_redis

import logging
import asyncio

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # === 启动 ===
    setup_logging(settings.debug)
    # 密钥校验:缺失或格式不对时启动即失败(给出生成命令)
    validate_secrets()

    # 数据库结构自举:建表/补列/建索引(幂等),用户无需手动建库
    from .db.bootstrap import ensure_schema

    await ensure_schema()
    logger.info(f"🚀 {settings.app_name} 启动中...")

    # 检查 Neo4j 连接
    try:
        await neo4j_client.verify_connectivity()
        logger.info("✅ Neo4j 连接成功")
    except Exception as e:
        logger.warning(f"⚠️ Neo4j 连接失败: {e}")

    # 兴趣图谱约束(幂等;失败不影响启动)
    try:
        from .core.agent.interest.graph_repo import InterestGraphRepo

        await InterestGraphRepo().ensure_constraints()
    except Exception as e:  # noqa: BLE001
        logger.warning("interest graph constraints init failed: %s", e)

    # 检查 Redis 连接
    try:
        from .db import get_redis
        r = await get_redis()
        await r.ping()
        logger.info("✅ Redis 连接成功")
    except Exception as e:
        logger.warning(f"⚠️ Redis 连接失败: {e}")

    # 后台任务靠 worker 消费:启动时探测一次,没起就明确告警(避免"功能看起来没反应")
    try:
        from .tasks.dispatch import worker_alive

        if not await asyncio.to_thread(worker_alive, 2.0):
            logger.warning(
                "⚠️ 没有检测到 Celery worker:兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新都不会执行。"
                "请另开终端启动:celery -A app.celery_app worker --pool=solo -l info(见 README)"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ 检测 Celery worker 失败(忽略): {e}")

    logger.info(f"✨ {settings.app_name} 启动完成")

    yield

    # === 关闭 ===
    logger.info("🛑 正在关闭服务...")
    await close_postgres()
    await neo4j_client.close()
    await close_redis()
    logger.info("👋 服务已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Bubble 🫧 — 你的个人 AI 生活助手",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request Context
    app.add_middleware(RequestContextMiddleware)

    # 注册路由
    app.include_router(api_router)
    app.include_router(auth_controller.router, prefix="/api")

    # 注册异常处理
    register_exception_handlers(app)

    return app


app = create_app()
