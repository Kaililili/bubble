"""兴趣抽取的消息缓冲:攒够 N 条 或 静默 M 秒再合并抽取一次。

为什么要缓冲:每条消息抽一次 = 每条一次(或多次)模型调用;把连续几条合并成一次,
既省调用,也能抽到跨消息的关系。缓冲放在 Redis(worker 重启不丢)。
"""
import json
import logging

from ..config import settings

logger = logging.getLogger(__name__)


def _list_key(user_id) -> str:
    return f"interest:batch:list:{user_id}"


def _timer_key(user_id) -> str:
    return f"interest:batch:timer:{user_id}"


async def push(user_id, entry: dict) -> dict:
    """把一条消息放进缓冲区;返回 {size, flush_now, need_timer}"""
    from ..db.redis import get_redis

    redis = await get_redis()
    await redis.rpush(_list_key(user_id), json.dumps(entry, ensure_ascii=False, default=str))
    size = int(await redis.llen(_list_key(user_id)))
    if settings.interest_batch_size <= 1:
        return {"size": size, "flush_now": True, "need_timer": False}
    if size >= settings.interest_batch_size:
        return {"size": size, "flush_now": True, "need_timer": False}
    # 静默计时:同一用户只保留一个待触发的定时器
    first = await redis.set(_timer_key(user_id), "1", nx=True, ex=max(30, settings.interest_batch_wait_seconds))
    return {"size": size, "flush_now": False, "need_timer": bool(first)}


async def drain(user_id, limit: int = 50) -> list:
    """取走并清空缓冲区(worker 消费);返回 [{message_id, conversation_id, text, occurred_at}]"""
    from ..db.redis import get_redis

    redis = await get_redis()
    raw = await redis.lrange(_list_key(user_id), 0, limit - 1)
    if raw:
        await redis.ltrim(_list_key(user_id), len(raw), -1)
    await redis.delete(_timer_key(user_id))
    out = []
    for item in raw or []:
        try:
            out.append(json.loads(item))
        except Exception:  # noqa: BLE001
            continue
    return out
