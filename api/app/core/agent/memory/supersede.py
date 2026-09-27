"""显式 remember 普通事实的更新引擎。

流程:提取事实属性 → 混合召回候选(属性/向量/文本) → 模型对**每一条候选**批量判断关系
→ 代码校验后单事务写入(DUPLICATE 复用 / SUPERSEDE 失效 / COEXIST 并存 / 其余保留旧记录)。

思路参照 Mem0(先提取事实再检索旧记忆、模型只能从已召回 ID 里选)与
Graphiti(候选逐项比较、保留失效历史与来源),但不引入外部依赖、不迁移知识图谱。
"""
import json
import logging
import re
from uuid import UUID

from ....prompts.memory import FACT_ATTRIBUTE_PROMPT, FACT_RELATION_PROMPT

logger = logging.getLogger(__name__)

RELATIONS = ("DUPLICATE", "SUPERSEDE", "COEXIST", "UNCERTAIN")
MAX_CANDIDATES = 6

_SPACE_RE = re.compile(r"\s+")


def normalize_fact(text: str) -> str:
    """事实文本归一化(去空白),用于"完全相同"的幂等判断"""
    return _SPACE_RE.sub("", (text or "")).strip()


def _clean_json(text: str | None) -> dict | None:
    """从模型输出里抠出 JSON(容忍 ```json 包裹与前后废话)"""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    for candidate in (
        stripped,
        text[text.find("{") : text.rfind("}") + 1] if "{" in text else "",
    ):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            continue
    return None


def parse_fact_relations(text: str | None, valid_ids: set[str]) -> dict[str, str]:
    """解析模型输出的关系;只接受 valid_ids 里的候选,非法 ID / 未知关系一律忽略(默认不失效)"""
    data = _clean_json(text)
    if not data:
        return {}
    items = data.get("relations")
    if not isinstance(items, list):
        return {}
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        relation = str(item.get("relation") or "").strip().upper()
        if candidate_id in valid_ids and relation in RELATIONS:
            out[candidate_id] = relation
    return out


async def _invoke(model, prompt: str) -> str | None:
    from langchain_core.messages import HumanMessage

    try:
        result = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fact update model call failed: %s", exc)
        return None


async def _build_model(session, user_id):
    from app.core.llm.client import build_chat_model
    from app.core.llm.resolver import get_default_config

    try:
        config = await get_default_config(session, user_id, "chat")
        return build_chat_model(config, streaming=False, temperature=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build fact update model failed: %s", exc)
        return None


async def extract_fact_attribute(session, user_id, content, model=None) -> tuple[str | None, str | None]:
    """模型提取规范化"事实属性"与可选"适用范围";失败/不可靠返回 (None, None)"""
    if model is None:
        model = await _build_model(session, user_id)
    if model is None:
        return None, None
    raw = await _invoke(model, FACT_ATTRIBUTE_PROMPT.format(content=content))
    data = _clean_json(raw)
    if not data:
        return None, None
    attribute = (str(data.get("attribute") or "")).strip()[:50] or None
    scope = (str(data.get("scope") or "")).strip()[:100] or None
    return attribute, scope


async def judge_fact_relations(
    session,
    user_id,
    new_content,
    attribute,
    scope,
    candidates,
    model=None,
) -> dict[str, str]:
    """模型对每条候选批量判断关系;失败/非法输出时返回空(即全部保留旧记录)"""
    if not candidates:
        return {}
    if model is None:
        model = await _build_model(session, user_id)
    if model is None:
        return {}
    cand_desc = [
        {
            "id": str(c.id),
            "content": c.content,
            "attribute": getattr(c, "attribute", None),
            "scope": getattr(c, "scope", None),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in candidates
    ]
    prompt = FACT_RELATION_PROMPT.format(
        content=new_content,
        attribute=attribute or "",
        scope=scope or "",
        candidates=json.dumps(cand_desc, ensure_ascii=False),
    )
    raw = await _invoke(model, prompt)
    return parse_fact_relations(raw, {str(c.id) for c in candidates})


async def upsert_fact(
    session,
    user_id: UUID,
    content: str,
    *,
    embedding=None,
    source: str | None = None,
    source_message_id: UUID | None = None,
    model=None,
) -> tuple[str, object, list[str]]:
    """显式 remember 普通事实:一次事务内完成 去重/候选/判断/写入。

    返回 (outcome, memory, superseded_contents);outcome 为 'reused' 或 'created'。
    """
    from app.repositories.memory_repository import MemoryRepository

    repo = MemoryRepository(session)

    # 1. 完全相同(归一化后一致)的现行事实 → 复用,不新增第二条
    same = await repo.find_active_by_content(user_id, "fact", content)
    if same is not None:
        if embedding is not None:
            same.embedding = embedding
        if source_message_id:
            same.source = source
            same.source_message_id = source_message_id
        await repo.update(same)
        return "reused", same, []

    # 2. 提取属性(尽力而为;旧记录没有属性时靠向量/文本兜底召回)
    attribute, scope = await extract_fact_attribute(session, user_id, content, model)

    # 3. 混合召回候选(同用户、同类型、active)
    candidates = await repo.find_update_candidates(
        user_id, "fact", attribute, scope, embedding, content, limit=MAX_CANDIDATES
    )

    # 4. 批量判断(模型只提关系,代码校验;失败→空→全部保留)
    relations = await judge_fact_relations(
        session, user_id, content, attribute, scope, candidates, model
    )

    # 5. DUPLICATE → 复用旧记录(不新增)
    candidate_by_id = {str(c.id): c for c in candidates}
    for candidate_id, relation in relations.items():
        if relation != "DUPLICATE":
            continue
        old = candidate_by_id.get(candidate_id)
        if (
            old is not None
            and old.user_id == user_id
            and old.type == "fact"
            and old.status == "active"
        ):
            if embedding is not None:
                old.embedding = embedding
            if source_message_id:
                old.source = source
                old.source_message_id = source_message_id
            await repo.update(old)
            return "reused", old, []

    # 6. 创建新记忆(先 flush 拿 id,不 commit)
    new = await repo.insert_fact(
        user_id=user_id,
        content=content,
        embedding=embedding,
        source=source,
        source_message_id=source_message_id,
        attribute=attribute,
        scope=scope,
    )

    # 7. 应用 SUPERSEDE(逐条校验归属/类型/仍有效后标记;最后单事务提交)
    superseded_contents: list[str] = []
    for candidate_id, relation in relations.items():
        if relation != "SUPERSEDE":
            continue
        old = candidate_by_id.get(candidate_id)
        if (
            old is None
            or old.user_id != user_id
            or old.type != "fact"
            or old.status != "active"
        ):
            continue
        old.status = "superseded"
        old.superseded_by = new.id
        superseded_contents.append(old.content)

    await session.commit()
    return "created", new, superseded_contents


__all__ = [
    "RELATIONS",
    "MAX_CANDIDATES",
    "normalize_fact",
    "parse_fact_relations",
    "extract_fact_attribute",
    "judge_fact_relations",
    "upsert_fact",
]
