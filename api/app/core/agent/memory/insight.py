"""记忆洞察层:把零碎事实归纳成对用户的整体理解,常驻注入对话。

- 输入:高价值记忆 + 用户背景 + 兴趣主线(社区摘要) + 情绪趋势
- 输出:3~6 条洞察(theme / content / based_on / confidence / importance)
- 落库:memory_insights 按 theme upsert(同主题更新,不堆叠),content 向量化
- 触发:新增记忆/兴趣累计够多,且距上次洞察超过冷却天数(替代定时任务,不需要新基建)
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
from ....prompts.memory import REFLECT_PROMPT  # insight logger

MIN_NEW_ITEMS = 5
COOLDOWN_DAYS = 3
MAX_INSIGHTS = 6
MIN_CONTENT_CHARS = 8
MAX_CONTENT_CHARS = 200


def should_refresh(
    new_items: int,
    last_at: datetime | None,
    now: datetime | None = None,
    *,
    min_new: int = MIN_NEW_ITEMS,
    cooldown_days: int = COOLDOWN_DAYS,
) -> bool:
    """是否值得重算洞察:新增够多 且 过了冷却期。

    没有 last_at(第一次)时只看新增数量;冷却期防止短期频繁重算浪费调用。
    """
    if new_items < min_new:
        return False
    if last_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    return current - last_at >= timedelta(days=cooldown_days)


def normalize_insight(item: dict) -> dict | None:
    """清洗单条洞察:theme/content 必填,数值夹到合法区间,过长截断"""
    if not isinstance(item, dict):
        return None
    theme = (str(item.get("theme") or "")).strip()[:50]
    content = (str(item.get("content") or "")).strip()
    if not theme or len(content) < MIN_CONTENT_CHARS:
        return None
    based_on = [str(x).strip()[:60] for x in (item.get("based_on") or []) if str(x).strip()][:10]
    try:
        confidence = float(item.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6
    try:
        importance = int(item.get("importance", 5))
    except (TypeError, ValueError):
        importance = 5
    return {
        "theme": theme,
        "content": content[:MAX_CONTENT_CHARS],
        "based_on": based_on,
        "confidence": max(0.0, min(confidence, 1.0)),
        "importance": max(0, min(importance, 10)),
    }


def format_insight_block(insights: list, limit: int = 5) -> str:
    """拼装注入 system prompt 的洞察块;无洞察返回空串"""
    lines: list[str] = []
    for item in insights[:limit]:
        theme = getattr(item, "theme", None) or (item or {}).get("theme")
        content = (getattr(item, "content", None) or (item or {}).get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- {theme}:{content}" if theme else f"- {content}")
    if not lines:
        return ""
    return "[对用户的整体理解](由历史记忆归纳,可被用户纠正)\n" + "\n".join(lines)




async def collect_input(session, user_id) -> str:
    """拼装归纳输入:高价值记忆 + 背景 + 兴趣主线 + 情绪趋势(失败逐项降级)"""
    lines: list[str] = []
    try:
        from app.repositories.memory_repository import MemoryRepository, UserProfileRepository

        profiles = await UserProfileRepository(session).list_by_user(user_id)
        if profiles:
            lines.append("[用户背景]")
            lines.extend(f"{p.key}: {p.value}" for p in profiles[:15])
        memories = await MemoryRepository(session).list_top_for_insight(user_id, limit=20)
        if memories:
            lines.append("[记忆条目]")
            lines.extend(
                f"- [{m.type}] {m.content}" for m in memories if (m.content or "").strip()
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("insight input (memory) failed: %s", e)
    try:
        from app.models.interest_community_model import InterestCommunity
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(InterestCommunity).where(InterestCommunity.user_id == user_id)
            )
        ).scalars().all()
        rows = [r for r in rows if len(r.members or []) >= 2]
        rows.sort(key=lambda r: len(r.members or []), reverse=True)
        if rows:
            lines.append("[兴趣主线]")
            for row in rows[:4]:
                summary = (row.summary or "").strip()
                lines.append(f"- {row.name}: {summary}" if summary else f"- {row.name}")
    except Exception as e:  # noqa: BLE001
        logger.warning("insight input (interest) failed: %s", e)
    try:
        from app.core.agent.emotion.aggregator import aggregate_profile
        from app.repositories.emotion_repository import EmotionRepository

        snapshot_rows = await EmotionRepository(session).list_recent(user_id, days=14, limit=30)
        if snapshot_rows:
            profile = aggregate_profile(snapshot_rows)
            lines.append("[情绪趋势]")
            lines.append(
                f"主导情绪 {profile.dominant_emotion},均值效价 {profile.avg_valence:.2f},趋势 {profile.trend}"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("insight input (emotion) failed: %s", e)
    return "\n".join(lines)


async def generate_insights(session, user_id, model=None) -> list[dict]:
    """调模型归纳洞察;输入太少或失败返回空列表"""
    block = await collect_input(session, user_id)
    if len(block) < 60:
        return []
    if model is None:
        from app.core.llm.client import build_chat_model
        from app.core.llm.resolver import get_default_config

        config = await get_default_config(session, user_id, "chat")
        model = build_chat_model(config, streaming=False, temperature=0.5)
    try:
        from langchain_core.messages import HumanMessage

        prompt = REFLECT_PROMPT.replace("__BLOCK__", block)
        result = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(result, "content", result)
        raw = content if isinstance(content, str) else str(content)
    except Exception as e:  # noqa: BLE001
        logger.warning("insight generation failed: %s", e)
        return []

    from app.core.agent.interest.extractor import _parse_json

    data = _parse_json(raw)
    items = data.get("insights") if isinstance(data, dict) else None
    cleaned = [normalize_insight(item) for item in (items or [])]
    return [item for item in cleaned if item][:MAX_INSIGHTS]


async def upsert_insights(session, user_id, insights: list[dict]) -> int:
    """按 theme upsert:同主题更新而非堆叠"""
    if not insights:
        return 0
    from sqlalchemy import select, update

    from app.models.memory_insight_model import MemoryInsight

    created = 0
    for item in insights:
        existing = (
            await session.execute(
                select(MemoryInsight).where(
                    MemoryInsight.user_id == user_id, MemoryInsight.theme == item["theme"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                MemoryInsight(
                    user_id=user_id,
                    theme=item["theme"],
                    content=item["content"],
                    based_on=item["based_on"],
                    importance=item["importance"],
                    confidence=item["confidence"],
                )
            )
            created += 1
        else:
            await session.execute(
                update(MemoryInsight)
                .where(MemoryInsight.id == existing.id)
                .values(
                    content=item["content"],
                    based_on=item["based_on"],
                    importance=item["importance"],
                    confidence=item["confidence"],
                    updated_at=datetime.now(timezone.utc),
                )
            )
    await session.commit()
    return created


async def load_insight_block(session, user_id, limit: int = 5) -> str:
    """读洞察块(常驻注入用);失败返回空串"""
    try:
        from sqlalchemy import select

        from app.models.memory_insight_model import MemoryInsight

        rows = (
            await session.execute(
                select(MemoryInsight)
                .where(MemoryInsight.user_id == user_id)
                .order_by(MemoryInsight.importance.desc(), MemoryInsight.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("load insight block failed: %s", e)
        return ""
    return format_insight_block(list(rows), limit=limit)


async def count_new_items(session, user_id, since: datetime | None) -> int:
    """自上次洞察以来新增的记忆条数 + 兴趣提及数(用于触发节流)"""
    from sqlalchemy import func, select

    from app.models.interest_model import InterestMention
    from app.models.memory_model import Memory

    total = 0
    for model in (Memory, InterestMention):
        query = select(func.count()).select_from(model).where(model.user_id == user_id)
        if since is not None:
            query = query.where(model.created_at > since)
        total += int((await session.execute(query)).scalar_one() or 0)
    return total


async def last_insight_at(session, user_id):
    """上一次洞察的时间(没有则 None)"""
    from sqlalchemy import func, select

    from app.models.memory_insight_model import MemoryInsight

    value = await session.execute(
        select(func.max(MemoryInsight.updated_at)).where(MemoryInsight.user_id == user_id)
    )
    return value.scalar_one_or_none()


async def refresh_insights(session, user_id, model=None, force: bool = False) -> int:
    """归纳并落库;返回写入的洞察条数(0 表示未触发或失败)"""
    if not force:
        since = await last_insight_at(session, user_id)
        new_items = await count_new_items(session, user_id, since)
        if not should_refresh(new_items, since):
            return 0
    insights = await generate_insights(session, user_id, model=model)
    if not insights:
        return 0
    await upsert_insights(session, user_id, insights)
    logger.info("insights refreshed: %d items", len(insights))
    return len(insights)
