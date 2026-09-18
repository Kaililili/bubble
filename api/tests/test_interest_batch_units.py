"""兴趣批处理纯函数自测:拼接格式 / evidence 归属 / 按消息分组"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.interest.batch_utils import (
    attribute_entities,
    build_batch_text,
    group_by_entry,
)

E1 = {
    "message_id": "m1",
    "conversation_id": "c1",
    "text": "最近又开始打篮球了",
    "occurred_at": datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc),
}
E2 = {
    "message_id": "m2",
    "conversation_id": "c1",
    "text": "NBA 也一直在看,勇士队还是最喜欢",
    "occurred_at": datetime(2026, 9, 14, 21, 30, tzinfo=timezone.utc),
}


def test_build_batch_text() -> None:
    text = build_batch_text([E1, E2])
    lines = text.split(chr(10))
    assert len(lines) == 2
    # 行首是时间标记,不包含 message_id(避免污染 evidence)
    assert lines[0].startswith("[2026-09-10 20:00] ")
    assert "m1" not in text and "m2" not in text
    assert lines[1].endswith("勇士队还是最喜欢")
    print("build_batch_text ok")


def test_attribute_entities() -> None:
    entities = [
        {"key": "篮球", "evidence": "打篮球"},
        {"key": "nba", "evidence": "NBA 也一直在看"},
        {"key": "勇士队", "evidence": "勇士队还是最喜欢"},
        {"key": "无主实体", "evidence": "这句话不在任何一条消息里"},  # 应被丢弃
    ]
    owners = attribute_entities(entities, [E1, E2])
    assert owners["篮球"]["message_id"] == "m1"
    assert owners["nba"]["message_id"] == "m2"
    assert owners["勇士队"]["message_id"] == "m2"
    assert "无主实体" not in owners, "归属失败的实体必须丢弃,不能张冠李戴"
    print("attribute_entities ok")


def test_group_by_entry() -> None:
    entities = [
        {"key": "篮球", "evidence": "打篮球"},
        {"key": "nba", "evidence": "NBA"},
    ]
    relations = [{"from_key": "nba", "to_key": "篮球", "type": "broader", "evidence": "NBA"}]
    owners = attribute_entities(entities, [E1, E2])
    groups = group_by_entry(entities, relations, owners, [E1, E2])
    # 关系按其主语归属到 m2(归一化后的 evidence 匹配)
    assert len(groups) == 2
    assert groups[0]["entry"]["message_id"] == "m1"
    assert [e["key"] for e in groups[0]["entities"]] == ["篮球"]
    assert groups[1]["entry"]["message_id"] == "m2"
    print("group_by_entry ok")


if __name__ == "__main__":
    test_build_batch_text()
    test_attribute_entities()
    test_group_by_entry()
    print("ALL PASS")
