"""事实更新纯函数自测:归一化 / JSON 解析 / 关系输出解析(非法 ID 与未知关系一律忽略)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.memory.supersede import (  # noqa: E402
    normalize_fact,
    parse_fact_relations,
)


def test_normalize_fact() -> None:
    assert normalize_fact(" 我 住在 上海 ") == "我住在上海"
    assert normalize_fact("") == ""
    print("normalize fact ok")


def test_parse_relations() -> None:
    valid = {"11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"}
    out = parse_fact_relations(
        '{"relations": [{"candidate_id": "11111111-1111-1111-1111-111111111111", "relation": "SUPERSEDE"},'
        '{"candidate_id": "22222222-2222-2222-2222-222222222222", "relation": "COEXIST"}]}',
        valid,
    )
    assert out == {
        "11111111-1111-1111-1111-111111111111": "SUPERSEDE",
        "22222222-2222-2222-2222-222222222222": "COEXIST",
    }, out
    # 非法 ID 被忽略
    out = parse_fact_relations(
        '{"relations": [{"candidate_id": "not-a-real-id", "relation": "SUPERSEDE"}]}',
        valid,
    )
    assert out == {}
    # 未知关系被忽略
    out = parse_fact_relations(
        '{"relations": [{"candidate_id": "11111111-1111-1111-1111-111111111111", "relation": "DELETE"}]}',
        valid,
    )
    assert out == {}
    # 包裹 ```json 也能解析
    out = parse_fact_relations(
        '```json\n{"relations": [{"candidate_id": "11111111-1111-1111-1111-111111111111", '
        '"relation": "UNCERTAIN"}]}\n```',
        valid,
    )
    assert out == {"11111111-1111-1111-1111-111111111111": "UNCERTAIN"}
    # 空/非法输出 → 空
    assert parse_fact_relations("", valid) == {}
    assert parse_fact_relations("not json", valid) == {}
    print("parse relations ok")


if __name__ == "__main__":
    test_normalize_fact()
    test_parse_relations()
    print("ALL PASS")
