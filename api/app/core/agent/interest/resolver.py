"""实体消解第三层:向量相似 + LLM 判定。

规则层(dedup_key)只能处理字面差异(RAG检索项目/RAG);像"检索项目"与"RAG"这种
同一概念的不同说法,需要用 embedding 找候选、再让 LLM 裁决是否同一个实体。
阈值参考实测:bge-m3 同义/近义约 0.8+,"NBA vs 篮球"这类相关但不同约 0.6。
"""
import logging
import json

from langchain_core.messages import HumanMessage, SystemMessage
from ....prompts.interest import (
    DEDUP_AUDIT_PROMPT as _AUDIT_PROMPT,
    ENTITY_JUDGE_PROMPT as _JUDGE_PROMPT,
)

logger = logging.getLogger(__name__)

MERGE_SIM = 0.90  # 高于此值直接判定同一实体
JUDGE_SIM = 0.72  # 高于此值但低于 MERGE_SIM → 交给 LLM 裁决



async def judge_same_entity(model, name_a: str, name_b: str) -> bool:
    """让 LLM 裁决两个名字是否同一个实体;失败时返回 False(保守不合并)"""
    try:
        resp = await model.ainvoke(
            [
                SystemMessage(content=_JUDGE_PROMPT),
                HumanMessage(content=f"实体A:{name_a}\n实体B:{name_b}"),
            ]
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("entity judge failed: %s", e)
        return False
    content = resp.content
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    text = str(content).strip().lower()
    return text.startswith("yes") or text.startswith("是")


async def semantic_canonical(
    session,
    user_id,
    name: str,
    *,
    embedder,
    judge_model=None,
    top_k: int = 3,
    vector=None,
) -> tuple[str, str] | None:
    """用向量找候选、必要时让 LLM 裁决;返回 (canonical_key, canonical_name) 或 None"""
    if not name or embedder is None:
        return None
    from ....repositories.interest_repository import InterestRepository

    if vector is None:  # 调用方已算过就直接复用,避免同一名字重复 embedding
        try:
            vector = await embedder.aembed_query(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("entity name embedding failed: %s", e)
            return None
    try:
        pairs = await InterestRepository(session).search_by_vector(user_id, vector, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        logger.warning("entity vector search failed: %s", e)
        return None
    for node, sim in pairs:
        if node.name == name:
            continue
        if sim >= MERGE_SIM:
            return node.key, node.name
        if sim >= JUDGE_SIM and judge_model is not None:
            if await judge_same_entity(judge_model, name, node.name):
                return node.key, node.name
    return None




async def audit_duplicate_groups(model, names: list[str]) -> list[list[str]]:
    """整表审计:一次 LLM 调用找出重复实体分组(比相似度阈值可靠:上下位与同义难分)"""
    cleaned = sorted({n.strip() for n in names if n and n.strip()})
    if len(cleaned) < 2:
        return []
    try:
        resp = await model.ainvoke(
            [SystemMessage(content=_AUDIT_PROMPT), HumanMessage(content="、".join(cleaned))]
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("entity audit failed: %s", e)
        return []
    content = resp.content
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    text = str(content).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("entity audit JSON parse failed")
        return []
    name_set = set(cleaned)
    groups: list[list[str]] = []
    for group in data.get("groups") or []:
        if not isinstance(group, list):
            continue
        members = [str(g).strip() for g in group if str(g).strip() in name_set]
        if len(members) >= 2:
            groups.append(members)
    return groups
