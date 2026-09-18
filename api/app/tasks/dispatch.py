"""任务派发:统一决定走 Celery 队列还是进程内后台任务。

- `BACKGROUND_MODE=celery`:任务进 Redis 队列,进程重启不丢、失败自动重试(生产/Docker 默认)
- `BACKGROUND_MODE=inline`(默认):进程内 asyncio 任务,本地开发不需要额外起 worker
"""
import asyncio
import logging

from ..celery_app import celery_app  # noqa: F401  确保 shared_task 绑定到本项目应用
from ..config import settings

logger = logging.getLogger(__name__)


def using_celery() -> bool:
    return (settings.background_mode or "inline").lower() == "celery"


async def enqueue_interest(
    user_id, text: str, conversation_id=None, message_id=None, context_messages=None, task_set=None
) -> None:
    """把用户消息交给兴趣抽取:celery 模式先进缓冲区(攒够 N 条或静默 M 秒合并),inline 模式逐条"""
    if not text or user_id is None:
        return
    if using_celery():
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
            celery_app.send_task("interest.extract", args=[str(user_id), text, entry["conversation_id"], entry["message_id"], list(context_messages or [])])
            return
        if info.get("flush_now"):
            celery_app.send_task("interest.flush_batch", args=[str(user_id)])
        elif info.get("need_timer"):
            celery_app.send_task(
                "interest.flush_batch",
                args=[str(user_id)],
                countdown=int(settings.interest_batch_wait_seconds),
            )
        return
    from ..core.agent.interest.pipeline import extract_and_store

    _inline(
        extract_and_store(
            user_id,
            text,
            conversation_id,
            message_id=message_id,
            context_messages=context_messages,
        ),
        task_set,
        "interest",
    )

def enqueue_emotion(user_id, text: str, conversation_id=None, message_id=None, task_set=None) -> None:
    if not text or user_id is None:
        return
    if using_celery():
        celery_app.send_task(
            "emotion.analyze",
            args=[
                str(user_id),
                text,
                str(conversation_id) if conversation_id else None,
                str(message_id) if message_id else None,
            ],
        )
        return
    from ..core.agent.emotion.pipeline import analyze_and_store

    _inline(
        analyze_and_store(user_id, text, conversation_id, message_id), task_set, "emotion"
    )


def enqueue_summary(conversation_id, task_set=None) -> None:
    if conversation_id is None:
        return
    if using_celery():
        celery_app.send_task("memory.summarize", args=[str(conversation_id)])
        return
    from ..core.agent.memory.summarizer import run_summary_task

    _inline(run_summary_task(conversation_id), task_set, "summary")


def enqueue_insight(user_id, task_set=None) -> None:
    if user_id is None:
        return
    if using_celery():
        celery_app.send_task("memory.refresh_insight", args=[str(user_id)])
        return
    from ..core.agent.memory.insight import run_insight_task

    _inline(run_insight_task(user_id), task_set, "insight")


def _inline(coro, task_set, label: str) -> None:
    """进程内模式:创建 asyncio 任务,失败只记日志"""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError as exc:  # 没有事件循环(理论上不会走到)
        logger.warning("inline %s task not scheduled: %s", label, exc)
        return
    if task_set is not None:
        task_set.add(task)
        task.add_done_callback(task_set.discard)
