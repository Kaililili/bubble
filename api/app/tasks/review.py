"""个人回顾任务:

- `review.generate`:单个用户的回顾(对话工具受理后触发),完成后把报告写回会话;
- `review.weekly`:beat 每周日给近 7 天有活动的用户各生成一份并落地成记忆。

为什么放队列:一次回顾要调 3 次模型(实测约 30s),不能让它阻塞聊天主链路。
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import shared_task

from ..celery_app import celery_app  # noqa: F401  确保 shared_task 绑定到本项目应用
from .runtime import run_async

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
MAX_USERS = 200


def _format_reply(result: dict) -> str:
    """把回顾结果整理成一条会话消息(报告 + 简短的过程说明)"""
    report = (result.get("report") or "").strip() or "(本次回顾没有产出内容)"
    plan_desc = " → ".join(step["type"] for step in result.get("plan") or [])
    footer = [f"（多步任务执行计划:{plan_desc or '(空)'};重规划 {result.get('replans', 0)} 次）"]
    if result.get("degraded"):
        footer.append("数据缺口:" + ";".join(result["degraded"]))
    return report + "\n\n---\n" + "\n".join(footer)


async def _write_back(session, user_id: UUID, conversation_id: UUID | None, content: str) -> None:
    """把结果作为一条助手消息写回会话(顺带刷新会话活跃时间)"""
    if conversation_id is None:
        return
    from ..repositories.conversation_repository import ConversationRepository
    from ..repositories.message_repository import MessageRepository

    conversation = await ConversationRepository(session).get_by_id(conversation_id, user_id)
    if conversation is None:
        logger.warning("review write-back skipped: conversation %s not found", conversation_id)
        return
    await MessageRepository(session).create(
        conversation_id,
        role="assistant",
        content=content,
        metadata={"source": "weekly_review", "async": True},
    )
    conversation.updated_at = datetime.now(timezone.utc)
    await session.commit()


async def run_generate_review(
    user_id: UUID, conversation_id: UUID | None = None, days: int = WINDOW_DAYS, persist: bool = True
) -> dict:
    """任务体(独立函数,便于直接测试):跑 Plan-Execute 图 → 写回会话消息"""
    from ..core.agent.plan import run_review
    from ..core.agent.tools.builtin.review_tools import _clear_pending
    from ..db.postgres import async_session

    try:
        async with async_session() as session:
            result = await run_review(session, user_id, days=int(days), persist=bool(persist))
            reply = _format_reply(result)
            await _write_back(session, user_id, conversation_id, reply)
            logger.info(
                "review generated for %s: report=%s chars, replans=%s, degraded=%s",
                user_id,
                len(result.get("report") or ""),
                result.get("replans"),
                len(result.get("degraded") or []),
            )
            return {
                "report_chars": len(result.get("report") or ""),
                "written_back": conversation_id is not None,
                "replans": result.get("replans", 0),
                "degraded": len(result.get("degraded") or []),
            }
    finally:
        await _clear_pending(user_id)


@shared_task(name="review.generate")
def generate_review_task(
    user_id: str, conversation_id: str | None = None, days: int = WINDOW_DAYS, persist: bool = True
) -> dict:
    """单用户回顾:celery 入口(逻辑在 run_generate_review)"""
    return run_async(
        run_generate_review(
            UUID(str(user_id)),
            UUID(str(conversation_id)) if conversation_id else None,
            int(days),
            bool(persist),
        )
    )


async def run_weekly_reviews() -> dict:
    """任务体:给近 7 天有活动的用户各生成一份回顾(persist=True)"""
    from sqlalchemy import select

    from ..core.agent.plan import run_review
    from ..db.postgres import async_session
    from ..models.emotion_model import EmotionSnapshot
    from ..models.interest_model import InterestNode
    from ..models.memory_model import Memory

    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    user_ids: set = set()
    async with async_session() as session:
        for stmt in (
            select(EmotionSnapshot.user_id).where(EmotionSnapshot.created_at >= since),
            select(InterestNode.user_id).where(InterestNode.last_seen >= since),
            select(Memory.user_id).where(Memory.created_at >= since, Memory.type != "credential"),
        ):
            user_ids |= set((await session.execute(stmt.limit(MAX_USERS))).scalars().all())

    done, failed = 0, 0
    for uid in list(user_ids)[:MAX_USERS]:
        async with async_session() as session:
            try:
                result = await run_review(session, uid, days=WINDOW_DAYS, persist=True)
                if result.get("report"):
                    done += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("weekly review failed for %s: %s", uid, exc)
    return {"users": len(user_ids), "generated": done, "failed": failed}


@shared_task(name="review.weekly")
def weekly_review_task() -> dict:
    """beat 每周日触发(逻辑在 run_weekly_reviews)"""
    return run_async(run_weekly_reviews())
