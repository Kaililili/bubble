"""兴趣抽取批处理:把连续多条消息拼成一段文本,再把抽取结果归属回各自的消息。

纯函数,便于单测:拼接格式固定为 `[时间][消息id] 原话`,抽取结果按 evidence 归属。
"""
from datetime import datetime

from .extractor import _normalized_text


def build_batch_text(entries: list) -> str:
    """把一批消息拼成带时间与 id 的文本(供一次 LLM 抽取)"""
    lines = []
    for item in entries:
        when = item.get("occurred_at")
        stamp = when.strftime("%Y-%m-%d %H:%M") if isinstance(when, datetime) else ""
        lines.append(f"[{stamp}] {item.get('text', '').strip()}")
    return chr(10).join(lines)


def attribute_entities(entities: list, entries: list) -> dict:
    """把抽出的实体按 evidence 归属到具体那条消息。

    返回 {entity_key: entry};找不到归属的实体丢弃(避免张冠李戴)。
    """
    owners: dict = {}
    for entity in entities or []:
        key = entity.get("key")
        evidence = _normalized_text(str(entity.get("evidence") or ""))
        if not key or not evidence:
            continue
        for entry in entries:
            if evidence in _normalized_text(str(entry.get("text") or "")):
                owners[key] = entry
                break
    return owners


def group_by_entry(entities: list, relations: list, owners: dict, entries: list) -> list:
    """按归属把实体/关系分组到各自消息(用于逐条写库,保证 message_id 与时间正确)"""
    buckets: list = [{"entry": e, "entities": [], "relations": []} for e in entries]
    index = {id(e): i for i, e in enumerate(entries)}
    for entity in entities or []:
        entry = owners.get(entity.get("key"))
        if entry is not None:
            buckets[index[id(entry)]]["entities"].append(entity)
    for relation in relations or []:
        entry = owners.get(relation.get("from_key")) or owners.get(relation.get("to_key"))
        if entry is not None:
            buckets[index[id(entry)]]["relations"].append(relation)
    return [b for b in buckets if b["entities"] or b["relations"]]
