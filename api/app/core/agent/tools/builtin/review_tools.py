"""个人回顾工具:多步任务**受理即返回**,真正生成丢给 Celery,完成后写回当前会话。

为什么不在对话里同步跑:一次回顾要调 3 次模型(实测约 30s),
同步执行会让用户盯着没有输出的界面干等。这跟项目既有原则一致——
聊天主链路只做"读上下文 → 调模型 → 流式返回",重活全部丢给队列。
"""
import logging

from pydantic import BaseModel, Field

from ..base import ToolContext, register_tool

logger = logging.getLogger(__name__)

PENDING_KEY = "review:pending:{user_id}"
# 兜底有效期:正常路径由任务结束时清理;worker 被强杀时,最多挡住 5 分钟,不会一直卡住
PENDING_TTL_SECONDS = 300


async def _mark_pending(user_id) -> bool:
    """同一用户同时只允许一个回顾在生成(Redis 不可用时放行)"""
    try:
        from .....db.redis import get_redis

        redis = await get_redis()
        ok = await redis.set(PENDING_KEY.format(user_id=user_id), "1", ex=PENDING_TTL_SECONDS, nx=True)
        return bool(ok)
    except Exception as exc:  # noqa: BLE001
        logger.warning("review pending flag unavailable: %s", exc)
        return True


async def _clear_pending(user_id) -> None:
    try:
        from .....db.redis import get_redis

        redis = await get_redis()
        await redis.delete(PENDING_KEY.format(user_id=user_id))
    except Exception:  # noqa: BLE001
        pass


class WeeklyReviewArgs(BaseModel):
    days: int = Field(7, ge=1, le=30, description="回顾窗口天数,默认 7 天")
    persist: bool = Field(False, description="是否把回顾结果存成一条记忆(默认不存)")


@register_tool(
    "weekly_review",
    "生成用户最近一段时间的个人回顾(周报):按计划收集情绪、兴趣与记忆,交叉分析后写成报告。"
    "当用户说「帮我看看我最近过得怎么样」「生成我的周报/月度总结」「最近有什么变化」时调用。"
    "这是多步任务,调用后立即返回受理结果,报告会在生成完成后发到当前对话里,"
    "请告知用户稍等片刻,不要重复调用。",
    WeeklyReviewArgs,
)
async def weekly_review(ctx: ToolContext, days: int = 7, persist: bool = False) -> str:
    from .....celery_app import celery_app

    if not await _mark_pending(ctx.user_id):
        return "已经有一份回顾在生成中,完成后会发到本对话,请稍等,不要重复发起。"

    try:
        celery_app.send_task(
            "review.generate",
            args=[
                str(ctx.user_id),
                str(ctx.conversation_id) if ctx.conversation_id else None,
                int(days),
                bool(persist),
            ],
        )
    except Exception as exc:  # noqa: BLE001  队列不可用时同步兜底,保证功能可用
        logger.warning("review enqueue failed, fallback to sync: %s", exc)
        await _clear_pending(ctx.user_id)
        from .....core.agent.plan import run_review

        result = await run_review(ctx.session, ctx.user_id, days=days, persist=persist)
        return (result.get("report") or "(没有产出内容)").strip()

    return (
        f"已受理:正在生成近 {days} 天的个人回顾(要跑多步任务、调几次模型,大约需要半分钟)。"
        "完成后我会把报告发到本对话里,你可以先继续聊别的。"
    )


__all__ = ["weekly_review"]
