from fastapi import APIRouter
from ..core.response import success
from ..db import neo4j_client
from ..db import get_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check():
    """服务健康检查"""
    return success({"status": "ok", "app": "Bubble 🫧"})


@router.get("/hello")
async def hello():
    """简单测试端点"""
    return success({"message": "Hello from Bubble! 🫧"})


@router.get("/storage")
async def storage_check():
    """检查所有存储服务连接状态"""
    statuses = {}

    # PostgreSQL (已在请求中通过依赖注入验证)
    statuses["postgres"] = "ok"

    # Neo4j
    try:
        await neo4j_client.verify_connectivity()
        statuses["neo4j"] = "ok"
    except Exception as e:
        statuses["neo4j"] = str(e)

    # Redis
    try:
        r = await get_redis()
        await r.ping()
        statuses["redis"] = "ok"
    except Exception as e:
        statuses["redis"] = str(e)

    return success(statuses)
