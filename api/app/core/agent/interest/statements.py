"""Statement 溯源层:把抽取时的原句证据提升成图节点(纯函数,可单测)。

关键取舍:证据句在抽取阶段就已经拿到了(每个实体/关系自带 evidence 且通过接地校验),
所以这里不需要再调一次模型,只是把已有文本整理成图节点。
同一句话里提到的多个实体聚合到同一个 Statement,避免重复节点。
"""
import hashlib
import re

_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").strip())


def statement_id(text: str, message_id=None) -> str:
    """Statement 稳定唯一键:同一消息里的同一句话恒等,便于 MERGE 幂等"""
    raw = f"{message_id or ''}|{normalize_text(text)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _new_statement(sid: str, text: str, occurred_at, message_id, conversation_id) -> dict:
    when = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else occurred_at
    return {
        "sid": sid,
        "text": text,
        "entity_keys": [],
        "occurred_at": when,
        "message_id": str(message_id) if message_id else None,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


def build_statements(
    entities: list[dict] | None,
    relations: list[dict] | None,
    *,
    raw_text: str = "",
    occurred_at=None,
    message_id=None,
    conversation_id=None,
    canon=None,
) -> list[dict]:
    """从一轮抽取结果构造 Statement 列表。

    entities/relations 里的 evidence 就是原句片段;canon 把 key 映射到消解后的最终 key。
    """
    fix = canon or (lambda value: value)
    by_id: dict[str, dict] = {}

    def ensure(text: str) -> dict:
        sid = statement_id(text, message_id)
        item = by_id.get(sid)
        if item is None:
            item = _new_statement(sid, text, occurred_at, message_id, conversation_id)
            by_id[sid] = item
        return item

    for entity in entities or []:
        key = fix(entity.get("key"))
        text = normalize_text(entity.get("evidence") or "")
        if not key or not text:
            continue
        item = ensure(text)
        if key not in item["entity_keys"]:
            item["entity_keys"].append(key)

    for relation in relations or []:
        text = normalize_text(relation.get("evidence") or "")
        if not text:
            continue
        item = ensure(text)
        for key in (fix(relation.get("from_key")), fix(relation.get("to_key"))):
            if key and key not in item["entity_keys"]:
                item["entity_keys"].append(key)

    return [item for item in by_id.values() if item["entity_keys"]]
