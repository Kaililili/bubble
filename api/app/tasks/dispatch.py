"""任务派发:后台任务统一投递到 Celery 队列(Redis),由 worker 消费。

聊天主链路只负责「读上下文 → 调模型 → 流式返回」,兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新
都在回复结束后投递到队列:

- 消息在 Redis 里,进程重启任务不丢;
- 失败自动重试(指数退避);
- 所以**必须有一个 worker 在跑**,否则任务只会堆在队列里 —— 服务启动时会探测一次并告警。
"""
import logging

from ..celery_app import celery_app  # noqa: F401  确保 shared_task 绑定到本项目应用
from ..config import settings

logger = logging.getLogger(__name__)


async def enqueue_interest(
    user_id, text: str, conversation_id=None, message_id=None, context_messages=None
) -> None:
    """兴趣抽取:先进缓冲区,攒够 N 条 或 静默 M 秒后合并成一次抽取"""
    if not text or user_id is None:
        return
    from datetime import datetime, timezone

    from .batching import push

    entry = {
        "message_id": str(message_id) if message_id else None,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "text": text,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        info = await push(user_id, entry)
    except Exception as exc:  # noqa: BLE001  缓冲区不可用时退回逐条抽取
        logger.warning("interest buffer unavailable, fallback to single: %s", exc)
        celery_app.send_task(
            "interest.extract",
            args=[
                str(user_id),
                text,
                entry["conversation_id"],
                entry["message_id"],
                list(context_messages or []),
            ],
        )
        return
    if info.get("flush_now"):
        celery_app.send_task("interest.flush_batch", args=[str(user_id)])
    elif info.get("need_timer"):
        celery_app.send_task(
            "interest.flush_batch",
            args=[str(user_id)],
            countdown=int(settings.interest_batch_wait_seconds),
        )


def enqueue_emotion(user_id, text: str, conversation_id=None, message_id=None) -> None:
    if not text or user_id is None:
        return
    celery_app.send_task(
        "emotion.analyze",
        args=[
            str(user_id),
            text,
            str(conversation_id) if conversation_id else None,
            str(message_id) if message_id else None,
        ],
    )


def enqueue_summary(conversation_id) -> None:
    if conversation_id is None:
        return
    celery_app.send_task("memory.summarize", args=[str(conversation_id)])


def enqueue_insight(user_id) -> None:
    if user_id is None:
        return
    celery_app.send_task("memory.refresh_insight", args=[str(user_id)])


def worker_alive(timeout: float = 2.0) -> bool:
    """探测是否有 worker 在线(启动时用来给出明确告警,而不是静默不干活)"""
    try:
        return bool(celery_app.control.ping(timeout=timeout))
    except Exception as exc:  # noqa: BLE001
        logger.warning("celery ping failed: %s", exc)
        return False
