"""事实时效与失效:让被新事实取代的旧记忆不再干扰回答(不物理删除)。

策略:规则优先,只有"高度相似但不确定是不是同一件事"的歧义对才请 LLM 裁决,
每次写入最多一次裁决调用,控制成本。
"""
import logging
import re

logger = logging.getLogger(__name__)
from ....prompts.memory import SUPERSEDE_PROMPT

# 相似到这个程度才值得问模型(否则直接放行,避免无谓调用)
AMBIGUOUS_SIM = 0.5
_SPACE_RE = re.compile(r"\s+")



def normalize_fact(text: str) -> str:
    return _SPACE_RE.sub("", (text or "")).strip()


def bigram_jaccard(a: str, b: str) -> float:
    """字符二元组 Jaccard 相似度(中文短句上比词切分更稳)"""
    na, nb = normalize_fact(a), normalize_fact(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga = {na[i:i + 2] for i in range(len(na) - 1)} or {na}
    gb = {nb[i:i + 2] for i in range(len(nb) - 1)} or {nb}
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


# 槽位关键词:同一类槽位的不同取值(如"住在上海"与"搬到杭州")在字面上几乎不重合,
# 光靠相似度抓不到,必须靠槽位判断 —— 这类"同一件事换了值"正是最需要失效处理的场景。
SLOTS = {
    "居住": ("住在", "搬到", "搬家", "定居", "生活在"),
    "工作": ("工作", "就职", "入职", "实习", "跳槽", "公司"),
    "学习": ("在学", "在读", "备考", "考研", "自学"),
    "偏好": ("喜欢", "最爱", "迷上", "入坑", "习惯"),
}


def slot_of(text: str) -> str | None:
    """这句事实属于哪一类槽位(居住/工作/学习/偏好);判不出返回 None"""
    value = normalize_fact(text)
    for slot, keywords in SLOTS.items():
        if any(word in value for word in keywords):
            return slot
    return None


def decide_supersede_rules(new_text: str, old_text: str) -> str:
    """规则判定:supersede(直接失效) / ambiguous(交模型) / keep(互不相干)"""
    new_norm, old_norm = normalize_fact(new_text), normalize_fact(old_text)
    if not new_norm or not old_norm:
        return "keep"
    if new_norm == old_norm:
        return "supersede"
    if old_norm in new_norm or new_norm in old_norm:
        return "supersede"
    new_slot, old_slot = slot_of(new_norm), slot_of(old_norm)
    if new_slot is not None and new_slot == old_slot:
        return "ambiguous"
    if bigram_jaccard(new_norm, old_norm) >= AMBIGUOUS_SIM:
        return "ambiguous"
    return "keep"


def is_supersede_answer(text: str) -> bool:
    value = (text or "").strip().upper()
    return "SUPERSEDE" in value and "KEEP" not in value.replace("SUPERSEDE", "")


async def judge_supersede(model, new_text: str, old_text: str) -> bool:
    """歧义对交模型裁决;失败按不失效处理(保守,不误杀记忆)"""
    from langchain_core.messages import HumanMessage

    prompt = SUPERSEDE_PROMPT + "\n旧:" + old_text + "\n新:" + new_text
    try:
        result = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(result, "content", result)
        return is_supersede_answer(content if isinstance(content, str) else str(content))
    except Exception as exc:  # noqa: BLE001
        logger.warning("supersede judge failed: %s", exc)
        return False


async def apply_supersede(session, user_id, new_memory, embedding=None, model=None) -> list:
    """把被新事实取代的旧记忆标记为 superseded;返回被标记的旧内容列表"""
    from app.repositories.memory_repository import MemoryRepository

    repo = MemoryRepository(session)
    try:
        candidates = await repo.search_candidates(
            user_id, embedding, new_memory.content, limit=5, include_superseded=False
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("supersede candidates failed: %s", exc)
        return []
    marked = []
    judged = False
    for old, _sim in candidates:
        if old.id == new_memory.id or old.type != new_memory.type:
            continue
        action = decide_supersede_rules(new_memory.content, old.content)
        if action == "keep":
            continue
        if action == "ambiguous":
            if judged:
                continue
            judged = True
            if model is None:
                model = await _build_judge(session, user_id)
            if model is None or not await judge_supersede(model, new_memory.content, old.content):
                continue
        try:
            await repo.supersede(old, new_memory.id)
            marked.append(old.content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mark superseded failed: %s", exc)
    return marked


async def _build_judge(session, user_id):
    try:
        from app.core.llm.client import build_chat_model
        from app.core.llm.resolver import get_default_config

        config = await get_default_config(session, user_id, "chat")
        return build_chat_model(config, streaming=False, temperature=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build supersede judge failed: %s", exc)
        return None
