"""图谱抽取:受控 schema + 证据接地 + 补漏轮次。

设计依据(docs/INTEREST_EXTRACTION_RESEARCH.md):
- 实体类型走白名单(参考 GraphRAG `entity_types`),模型不得自创类型;
- 每个实体/关系必须给 evidence(原句连续片段),解析时做子串校验,不通过直接丢弃;
- 默认追加 1 轮 gleaning 补漏(参考 GraphRAG CONTINUE_PROMPT)。

注意:不再区分"兴趣 / 实体"——所有名词都是 Entity,"是否关注"由 is_followed 表达。
"""
import json
import logging
import re
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from .context_window import build_context_block
from ....prompts.interest import (
    BATCH_INSTRUCTION,
    EXTRACT_GLEAN_PROMPT as _GLEAN_PROMPT,
    EXTRACT_SYSTEM_PROMPT as _SYSTEM_PROMPT,
    MAX_ENTITIES,
    MAX_RELATIONS,
    RELATION_TYPES,
)
from .normalizer import (
    ENTITY_TYPES,
    coerce_category,
    coerce_entity_type,
    normalize_key,
    normalize_name,
    parse_time_expr,
)

logger = logging.getLogger(__name__)

INTEREST_HINTS = (
    "喜欢", "迷上", "入坑", "关注", "最近在", "一直在", "最近", "这阵子",
    "追", "在玩", "在看", "在听", "在读", "在学", "研究", "收藏", "打算", "准备",
    "爱好", "兴趣", "常看", "常玩",
)

# 纯寒暄/应答:没有信息量,不值得调用模型
_SKIP_EXACT = {
    "你好", "您好", "谢谢", "谢谢你", "好的", "好", "嗯", "嗯嗯", "在吗", "在么",
    "hi", "hello", "ok", "okay", "收到", "哈哈", "哈哈哈", "没问题", "谢谢啦",
}

_POSITIVE_HINTS = (
    "喜欢", "迷上", "入坑", "开始", "最近在", "一直在", "在看", "在玩", "在听",
    "在读", "在学", "追", "常看", "常玩",
)
_QUESTION_RE = re.compile(r"[?？]|是不是|有没有|哪些|什么时候|什么时间段|吗\s*$")
_SENSITIVE_WORDS = ("密码", "验证码", "token", "密钥", "银行卡", "身份证", "信用卡")

MAX_GLEANINGS = 1
GLEAN_MIN_CHARS = 30
# O2:短句不补漏(补漏是第二次 LLM 调用,短句几乎不会漏)





def should_extract(text: str, known_names: tuple[str, ...] | list[str] = ()) -> bool:
    """规则预筛:只挡明显无信息量的消息,其余交给模型判断。

    (早期版本要求命中兴趣信号词才抽,会把"开始坚持夜跑""天冷了跑步先停了"这类
    陈述句漏掉;抽取是后台任务,这里放宽、宁可多跑一次模型。)
    """
    value = (text or "").strip()
    if len(value) < 6:
        return False
    if any(word in value for word in _SENSITIVE_WORDS):
        return False
    if value.lower().strip("。.!！?？~ ") in _SKIP_EXACT:
        return False
    # 问句(尤其"我以前是不是关注过X")只是检索意图,不该当成新的图谱输入
    if _QUESTION_RE.search(value) and not any(hint in value for hint in _POSITIVE_HINTS):
        return False
    return True


def _parse_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("interest extraction JSON parse failed")
        return {}


def _coerce_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if len(text) == 7:  # YYYY-MM
            year, month = text.split("-")
            return date(int(year), int(month), 1)
        return date.fromisoformat(text[:10])
    except (ValueError, TypeError):
        return None


_PUNCT_RE = re.compile(r"[\s,，。.;；:：!！?？\"'“”‘’()（）\[\]【】\-—_/]+")


def _normalized_text(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").lower())


def is_grounded(raw_text: str, evidence: str) -> bool:
    """证据接地校验:evidence 去空白标点后必须是原句的子串"""
    ev = _normalized_text(evidence)
    if not ev:
        return False
    return ev in _normalized_text(raw_text)


def normalize_extraction(data: dict, raw_text: str, base_date: date | None = None) -> dict:
    """校验/归一化 LLM 输出:实体类型受控 + evidence 接地 + 关系两端必须来自本次实体"""
    result: dict = {"entities": [], "relations": []}
    if not isinstance(data, dict):
        return result
    since_fallback, until_fallback = parse_time_expr(raw_text, base_date)

    by_key: dict[str, dict] = {}
    for raw_entity in (data.get("entities") or [])[:MAX_ENTITIES]:
        if not isinstance(raw_entity, dict):
            continue
        name = normalize_name(str(raw_entity.get("name") or ""))
        key = normalize_key(name)
        if not name or not key or key in by_key:
            continue
        if any(word in name for word in _SENSITIVE_WORDS):
            continue
        evidence = normalize_name(str(raw_entity.get("evidence") or ""))
        if not is_grounded(raw_text, evidence):
            continue  # 证据不在原句里 → 模型脑补,丢弃
        category = coerce_category(name, raw_entity.get("category"))
        entity_type = coerce_entity_type(name, raw_entity.get("type"), category)
        aliases = [
            normalize_name(str(a))
            for a in (raw_entity.get("aliases") or [])
            if isinstance(a, (str, int, float)) and normalize_name(str(a))
        ][:10]
        since = _coerce_date(raw_entity.get("since")) or since_fallback
        until = _coerce_date(raw_entity.get("until")) or until_fallback
        if since and until and until < since:
            until = None
        try:
            confidence = float(raw_entity.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        by_key[key] = {
            "name": name,
            "key": key,
            "type": entity_type,
            "category": category,
            "aliases": aliases,
            "description": normalize_name(str(raw_entity.get("description") or ""))[:200],
            "is_followed": bool(raw_entity.get("is_followed")),
            "since": since,
            "until": until,
            "confidence": max(0.0, min(confidence, 1.0)),
            "evidence": evidence,
        }

    relations: list[dict] = []
    for raw_rel in (data.get("relations") or [])[:MAX_RELATIONS]:
        if not isinstance(raw_rel, dict):
            continue
        src = normalize_key(str(raw_rel.get("from") or ""))
        dst = normalize_key(str(raw_rel.get("to") or ""))
        rel_type = normalize_name(str(raw_rel.get("type") or "related")).lower()
        evidence = normalize_name(str(raw_rel.get("evidence") or ""))
        # 关系类型受控 + 两端都必须是本次抽出的实体 + 证据必须接地
        if rel_type not in RELATION_TYPES:
            continue
        if src not in by_key or dst not in by_key or src == dst:
            continue
        if not is_grounded(raw_text, evidence):
            continue
        relations.append(
            {"from_key": src, "to_key": dst, "type": rel_type, "evidence": evidence}
        )

    # 互反关系去重:同一对实体只保留语义更具体的一条(part_of/member_of/broader > related > co_occur)
    rank = {"part_of": 3, "member_of": 3, "broader": 3, "related": 2, "co_occur": 1}
    unique_relations: dict[tuple[str, str], dict] = {}
    for rel in relations:
        pair = tuple(sorted((rel["from_key"], rel["to_key"])))
        current = unique_relations.get(pair)
        if current is None or rank.get(rel["type"], 0) > rank.get(current["type"], 0):
            unique_relations[pair] = rel

    result["entities"] = list(by_key.values())
    result["relations"] = list(unique_relations.values())
    return result


def _merge_extraction(base: dict, extra: dict) -> dict:
    """补漏轮结果合并:实体按 key 去重,关系按 (from,to,type) 去重"""
    merged = {"entities": list(base.get("entities") or []), "relations": list(base.get("relations") or [])}
    seen_keys = {e["key"] for e in merged["entities"]}
    for entity in extra.get("entities") or []:
        if entity["key"] not in seen_keys:
            merged["entities"].append(entity)
            seen_keys.add(entity["key"])
    seen_rel = {(r["from_key"], r["to_key"], r["type"]) for r in merged["relations"]}
    for rel in extra.get("relations") or []:
        token = (rel["from_key"], rel["to_key"], rel["type"])
        if token not in seen_rel:
            merged["relations"].append(rel)
            seen_rel.add(token)
    # 关系两端必须仍在实体集合里(补漏后可能新增实体,反过来不会失效)
    keys = {e["key"] for e in merged["entities"]}
    merged["relations"] = [
        r for r in merged["relations"] if r["from_key"] in keys and r["to_key"] in keys
    ]
    return merged


def _content_to_text(content) -> str:
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


async def extract_graph(
    model,
    raw_text: str,
    base_date: date | None = None,
    max_gleanings: int = MAX_GLEANINGS,
    known_entities: list[str] | None = None,
    context_messages: list[str] | None = None,
    batch: bool = False,
) -> dict:
    """调用 LLM 抽取实体与关系;失败返回空结构(不抛错)"""
    system_prompt = _SYSTEM_PROMPT
    if batch:  # 一次抽取多条消息时的输入说明
        system_prompt += BATCH_INSTRUCTION
    context_block = build_context_block(context_messages or [])
    if context_block:
        system_prompt += "\n" + context_block
    if known_entities:
        names = "、".join(sorted({n.strip() for n in known_entities if n and n.strip()})[:80])
        system_prompt += (
            f"\n已知实体(若句子里的对象就是其中之一,必须直接复用这个名称,不要造新名字):{names}\n"
        )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=raw_text[:2000])]
    try:
        first = await model.ainvoke(messages)
    except Exception as e:  # noqa: BLE001
        logger.warning("graph extraction LLM call failed: %s", e)
        return {"entities": [], "relations": []}
    result = normalize_extraction(_parse_json(_content_to_text(first.content)), raw_text, base_date)

    # O2:自适应补漏 —— 首轮没抽到东西、或句子很短时跳过第二次调用
    glean_rounds = max(0, min(int(max_gleanings or 0), 2))
    if not result["entities"] or len((raw_text or "").strip()) < GLEAN_MIN_CHARS:
        glean_rounds = 0
    for _ in range(glean_rounds):
        messages.append(HumanMessage(content=_GLEAN_PROMPT))
        try:
            more = await model.ainvoke(messages)
        except Exception as e:  # noqa: BLE001
            logger.warning("graph extraction gleaning failed: %s", e)
            break
        extra = normalize_extraction(_parse_json(_content_to_text(more.content)), raw_text, base_date)
        if not extra["entities"] and not extra["relations"]:
            break
        result = _merge_extraction(result, extra)
    return result
