"""步骤执行器:每种步骤类型一个确定性函数(输入相同 → 输出相同)。

这些是 Plan-Execute 里的"工具层":规划器只决定**做哪些步骤**,怎么做由这里写死的函数决定。
全部复用项目已有的聚合/检索能力,不重复实现。
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from .state import COLLECT_STEPS

logger = logging.getLogger(__name__)

MAX_MEMORY_ITEMS = 30
CONTENT_PREVIEW = 80


async def ask_model(session, user_id, prompt: str, *, temperature: float = 0.3) -> str:
    """调一次 chat 模型;未配置或失败返回空串(由调用方降级)"""
    from langchain_core.messages import HumanMessage

    from ...llm.client import build_chat_model
    from ...llm.resolver import get_default_config

    try:
        config = await get_default_config(session, user_id, "chat")
        model = build_chat_model(config, streaming=False, temperature=temperature)
        result = await model.ainvoke([HumanMessage(content=prompt)])
        text = getattr(result, "content", result)
        return text if isinstance(text, str) else str(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("review step model call failed: %r", f"{type(exc).__name__}: {exc}")
        return ""


def parse_json(text: str) -> dict | None:
    """从模型输出里抠 JSON(容忍 ```json 包裹与前后废话)"""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    for candidate in (stripped, text[text.find("{") : text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            continue
    return None


def _clip(text: str, size: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= size else text[:size].rstrip() + "..."


# ---------- collect 步骤 ----------


async def step_collect_emotion(session, user_id, args: dict, deps: dict) -> dict:
    """复用情绪模块的聚合能力,产出结构化的情绪摘要"""
    from ....core.agent.emotion.aggregator import aggregate_profile, emotion_distribution
    from ....repositories.emotion_repository import EmotionRepository

    days = int(args.get("days") or 7)
    rows = await EmotionRepository(session).list_recent(user_id, days=days, limit=300)
    if not rows:
        return {"status": "empty", "data": {"days": days, "count": 0}, "note": f"近 {days} 天没有情绪记录"}
    profile = aggregate_profile(rows)
    triggers = Counter(r.trigger for r in rows if r.trigger).most_common(3)
    data = {
        "days": days,
        "count": profile.sample_count,
        "dominant_emotion": profile.dominant_emotion,
        "avg_valence": profile.avg_valence,
        "avg_arousal": profile.avg_arousal,
        "trend": profile.trend,
        "negative_ratio": profile.negative_ratio,
        "distribution": emotion_distribution(rows)[:5],
        "top_triggers": [{"trigger": t, "count": c} for t, c in triggers],
    }
    data["sample_evidence"] = [
        {"emotion": r.emotion_type, "valence": r.valence, "trigger": r.trigger, "evidence": _clip(r.evidence, 60)}
        for r in rows[:3]
    ]
    return {"status": "ok", "data": data, "note": f"情绪记录 {profile.sample_count} 条,主导情绪 {profile.dominant_emotion}"}


async def step_collect_interests(session, user_id, args: dict, deps: dict) -> dict:
    """取兴趣图谱里这段时间活跃/新出现的实体(直接读物化索引,不跳图)"""
    from sqlalchemy import select

    from ....models.interest_model import InterestNode

    days = int(args.get("days") or 7)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(InterestNode)
        .where(InterestNode.user_id == user_id, InterestNode.last_seen >= since)
        .order_by(InterestNode.mention_count.desc())
        .limit(20)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return {"status": "empty", "data": {"days": days, "count": 0}, "note": f"近 {days} 天没有新的兴趣记录"}
    data = {
        "days": days,
        "count": len(rows),
        "items": [
            {
                "name": r.name,
                "category": r.category,
                "status": r.status,
                "mention_count": r.mention_count,
                "since": r.since.isoformat() if r.since else None,
                "until": r.until.isoformat() if r.until else None,
            }
            for r in rows[:12]
        ],
    }
    return {"status": "ok", "data": data, "note": f"这段时间活跃的兴趣 {len(rows)} 个"}


async def step_collect_memories(session, user_id, args: dict, deps: dict) -> dict:
    """取这段时间落库的长尾记忆与事件(凭证类不参与回顾)"""
    from sqlalchemy import select

    from ....models.memory_model import Memory

    days = int(args.get("days") or 7)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.created_at >= since,
            Memory.type != "credential",
        )
        .order_by(Memory.created_at.desc())
        .limit(MAX_MEMORY_ITEMS)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return {"status": "empty", "data": {"days": days, "count": 0}, "note": f"近 {days} 天没有新的记忆"}
    by_type = Counter(r.type for r in rows)
    data = {
        "days": days,
        "count": len(rows),
        "by_type": dict(by_type),
        "items": [
            {"type": r.type, "content": _clip(r.content, CONTENT_PREVIEW), "created_at": r.created_at.date().isoformat()}
            for r in rows[:12]
        ],
    }
    return {"status": "ok", "data": data, "note": f"这段时间新增记忆 {len(rows)} 条"}


# ---------- 分析 / 成文 / 落地 ----------


def _empty_notes(deps: dict) -> list[str]:
    return [d.get("note") for d in deps.values() if isinstance(d, dict) and not d.get("count")]


async def step_analyze(session, user_id, args: dict, deps: dict) -> dict:
    """交叉分析:一次模型调用;没有模型时用规则拼出可读结论"""
    from ....prompts.review import ANALYZE_PROMPT

    emotion = next((d for d in deps.values() if "dominant_emotion" in d), {})
    interests = next((d for d in deps.values() if "items" in d and "category" in json.dumps(d, ensure_ascii=False)), {})
    memories = next((d for d in deps.values() if "by_type" in d), {})
    days = int(emotion.get("days") or args.get("days") or 7)

    prompt = ANALYZE_PROMPT.format(
        days=days,
        emotion=json.dumps(emotion, ensure_ascii=False)[:2500] or "(无)",
        interests=json.dumps(interests, ensure_ascii=False)[:2000] or "(无)",
        memories=json.dumps(memories, ensure_ascii=False)[:2500] or "(无)",
    )
    answer = await ask_model(session, user_id, prompt)
    data = parse_json(answer)
    if data and isinstance(data.get("observations"), list) and data["observations"]:
        observations = [str(x) for x in data["observations"]][:5]
        highlights = [str(x) for x in (data.get("highlights") or [])][:2]
        concerns = [str(x) for x in (data.get("concerns") or [])][:2]
        source = "llm"
    else:
        observations = _rule_observations(emotion, interests, memories, days)
        highlights, concerns = [], _rule_concerns(emotion, memories)
        source = "rule"

    return {
        "status": "ok",
        "data": {
            "days": days,
            "source": source,
            "observations": observations,
            "highlights": highlights,
            "concerns": concerns,
            "missing": _empty_notes(deps),
        },
        "note": f"分析产出 {len(observations)} 条观察({source})",
    }


def _rule_observations(emotion: dict, interests: dict, memories: dict, days: int) -> list[str]:
    out: list[str] = []
    if emotion.get("count"):
        out.append(
            f"近 {days} 天有 {emotion['count']} 条情绪记录,主导情绪是{emotion.get('dominant_emotion')},"
            f"平均效价 {emotion.get('avg_valence')},趋势{emotion.get('trend')}。"
        )
        triggers = emotion.get("top_triggers") or []
        if triggers:
            out.append("最常出现的触发点是:" + "、".join(t["trigger"] for t in triggers[:3]) + "。")
    else:
        out.append(f"近 {days} 天没有情绪记录,这段时间的状态无从判断。")
    if interests.get("count"):
        names = "、".join(i["name"] for i in (interests.get("items") or [])[:5])
        out.append(f"兴趣上有 {interests['count']} 个活跃实体,包括 {names}。")
    else:
        out.append(f"近 {days} 天没有出现新的兴趣实体。")
    if memories.get("count"):
        out.append(f"新增记忆 {memories['count']} 条,类型分布 {memories.get('by_type')}。")
    else:
        out.append(f"近 {days} 天没有新增记忆。")
    return out


def _rule_concerns(emotion: dict, memories: dict) -> list[str]:
    concerns: list[str] = []
    if emotion.get("count") and (emotion.get("negative_ratio") or 0) >= 0.5:
        concerns.append(f"消极情绪占比 {emotion['negative_ratio']},偏高的信号。")
    if emotion.get("trend") == "down":
        concerns.append("情绪效价呈下行趋势。")
    return concerns[:2]


async def step_compose(session, user_id, args: dict, deps: dict) -> dict:
    """成文:一次模型调用;没有模型时按固定结构拼装"""
    from ....prompts.review import COMPOSE_PROMPT

    analysis = next((d for d in deps.values() if "observations" in d), {})
    days = int(analysis.get("days") or 7)
    data = {k: v for k, v in analysis.items() if k not in ("observations", "highlights", "concerns")}
    prompt = COMPOSE_PROMPT.format(
        days=days,
        analysis=json.dumps(analysis, ensure_ascii=False)[:3500],
        data=json.dumps(data, ensure_ascii=False)[:1500],
    )
    answer = await ask_model(session, user_id, prompt, temperature=0.4)
    report = answer.strip()
    if not report:
        report = _rule_report(analysis, days)
    return {"status": "ok", "data": {"days": days, "report": report}, "note": f"报告 {len(report)} 字"}


def _rule_report(analysis: dict, days: int) -> str:
    observations = analysis.get("observations") or []
    concerns = analysis.get("concerns") or []
    lines = [f"## 近 {days} 天回顾", ""]
    lines += [f"- {o}" for o in observations]
    if concerns:
        lines += ["", "**需要留意**"] + [f"- {c}" for c in concerns]
    lines += ["", "> 未配置对话模型,以上为规则汇总结果。"]
    return "\n".join(lines)


async def step_persist(session, user_id, args: dict, deps: dict) -> dict:
    """落地:把回顾存成一条记忆(供之后对话检索),失败不影响主流程"""
    from ....repositories.memory_repository import MemoryRepository

    report = ""
    for dep in deps.values():
        if isinstance(dep, dict) and dep.get("report"):
            report = dep["report"]
    if not report:
        return {"status": "empty", "data": {}, "note": "没有报告可落地"}
    content = _clip(report.replace("\n", " "), 400)
    try:
        memory = await MemoryRepository(session).create(
            user_id=user_id, type="event", content=f"个人回顾:{content}", importance=3
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("review persist failed: %s", exc)
        return {"status": "error", "data": {}, "note": f"落地失败:{exc}"}
    return {"status": "ok", "data": {"memory_id": str(memory.id)}, "note": "已存成一条记忆"}


STEP_REGISTRY = {
    "collect_emotion": step_collect_emotion,
    "collect_interests": step_collect_interests,
    "collect_memories": step_collect_memories,
    "analyze": step_analyze,
    "compose": step_compose,
    "persist": step_persist,
}

__all__ = ["STEP_REGISTRY", "ask_model", "parse_json", "COLLECT_STEPS"]
