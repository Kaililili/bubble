"""兴趣模块纯函数自测:归一化 / 时间解析 / 冷却 / 重排打分 / 证据组装 / 抽取解析

用法(api/ 目录下): ..\\.venv\\Scripts\\python.exe tests\\test_interest_units.py
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.interest.extractor import (
    _parse_json,
    is_grounded,
    normalize_extraction,
    should_extract,
)
from app.core.agent.interest.normalizer import (
    ENTITY_TYPES,
    coerce_category,
    coerce_entity_type,
    compute_status,
    dedup_key,
    infer_category,
    merge_aliases,
    normalize_key,
    parse_time_expr,
)
from app.core.agent.interest.retriever import (
    Candidate,
    fmt_range,
    format_evidence,
    heat_score,
    hop_weight,
    relation_terms,
    recency_score,
    score_candidate,
    query_terms,
)
from app.core.agent.interest.statements import build_statements, statement_id
from app.core.agent.interest.community import (
    group_members,
    label_propagation,
    merge_connected_communities,
)


def test_normalize() -> None:
    assert normalize_key("我最近迷上NBA了") == "nba"
    assert normalize_key(" 一直在看 篮球 ") == "篮球"
    assert normalize_key("美职篮") == "美职篮"
    assert infer_category("NBA") == "体育"
    assert infer_category("生椰拿铁") == "美食"
    assert infer_category("量子力学") == "其他"
    assert coerce_category("NBA", "乱写") == "体育"
    assert coerce_category("NBA", "音乐") == "音乐"
    assert merge_aliases(["美职篮"], ["NBA", "美职篮", ""]) == ["美职篮", "NBA"]
    # 实体消解键:剥通用修饰词后相同 → 同一实体;子类不合并
    assert dedup_key("RAG 检索项目") == dedup_key("RAG")
    assert dedup_key("大模型应用") == dedup_key("大模型")
    assert dedup_key("V60 滤杯") == dedup_key("V60")
    assert dedup_key("科幻电影") != dedup_key("电影")
    print("normalize ok")


def test_time_and_status() -> None:
    base = date(2026, 9, 12)
    assert parse_time_expr("2026年7月开始看NBA", base) == (date(2026, 7, 1), None)
    assert parse_time_expr("去年开始关注篮球", base) == (date(2025, 1, 1), None)
    assert parse_time_expr("前年看的CBA", base) == (date(2024, 1, 1), None)
    assert parse_time_expr("上个月开始喝咖啡", base) == (date(2026, 8, 1), None)
    since, _ = parse_time_expr("最近迷上NBA", base)
    assert since == base - timedelta(days=30)
    _, until = parse_time_expr("最近不看NBA了", base)
    assert until == base
    _, until2 = parse_time_expr("篮球最近不太看了", base)
    assert until2 == base
    assert parse_time_expr("随便聊聊", base) == (None, None)

    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    assert compute_status(date(2026, 9, 1), now, 3, now=now) == "cooled"
    assert compute_status(None, now, 3, now=now) == "active"
    assert compute_status(None, now - timedelta(days=120), 1, now=now) == "cooled"
    assert compute_status(None, now - timedelta(days=120), 5, now=now) == "active"
    print("time/status ok")


def test_scoring() -> None:
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    assert hop_weight(0) == 1.0 and hop_weight(2) == 0.35
    assert heat_score(0) == 0 and heat_score(5) > heat_score(1) and heat_score(50) <= 1.0
    assert recency_score(now, now) == 1.0
    assert recency_score(now - timedelta(days=60), now) == 0.6
    assert recency_score(now - timedelta(days=200), now) == 0.3

    seed = Candidate(key="nba", name="NBA", hops=0, vec_sim=1.0, mention_count=4, last_seen=now)
    one_hop = Candidate(key="basketball", name="篮球", hops=1, vec_sim=0.0, mention_count=6, last_seen=now)
    two_hop = Candidate(key="cba", name="CBA", hops=2, vec_sim=0.0, mention_count=1, last_seen=now)
    assert score_candidate(seed, now) > score_candidate(one_hop, now) > score_candidate(two_hop, now)
    print("scoring ok")


def test_query_terms() -> None:
    # 问句里的下挂实体要能被抽出来做实体反查
    assert "CBA" in query_terms("我看过CBA么")
    assert "库里" in query_terms("我还关注库里么")
    terms = query_terms("跟NBA相关的我还关注过什么?")
    assert any(t.upper() == "NBA" for t in terms)
    assert query_terms("") == []
    print("query terms ok")


def test_relation_terms() -> None:
    # 关系型问句:A 和 B 两侧都要切出来当最短路锚点
    assert relation_terms("篮球和手冲咖啡有什么关系吗") == ["篮球", "手冲咖啡"]
    assert relation_terms("大模型和马拉松有什么关系吗") == ["大模型", "马拉松"]
    assert relation_terms("手冲咖啡和咖啡是什么关系") == ["手冲咖啡", "咖啡"]
    assert relation_terms("Rust跟并发有联系么") == ["Rust", "并发"]
    assert relation_terms("") == []
    print("relation terms ok")


def test_statements() -> None:
    # Statement 唯一键:同一消息同一句话恒等,换消息或换句子即不同(幂等写的前提)
    assert statement_id("我最近在学 Rust", "m1") == statement_id("我最近在学 Rust", "m1")
    assert statement_id("我最近在学 Rust", "m1") != statement_id("我最近在学 Rust", "m2")
    assert statement_id("我最近在学 Rust") != statement_id("我在学 tokio")

    entities = [
        {"key": "rust", "evidence": "最近在学 Rust"},
        {"key": "所有权", "evidence": "最近在学 Rust"},
        {"key": "tokio", "evidence": "顺便看了 tokio"},
    ]
    relations = [{"from_key": "tokio", "to_key": "rust", "evidence": "顺便看了 tokio"}]
    built = build_statements(entities, relations, message_id="m1")
    assert len(built) == 2
    by_text = {item["text"]: item for item in built}
    assert sorted(by_text["最近在学 Rust"]["entity_keys"]) == ["rust", "所有权"]
    assert sorted(by_text["顺便看了 tokio"]["entity_keys"]) == ["rust", "tokio"]
    assert build_statements([{"key": "x", "evidence": ""}], None, message_id="m1") == []
    merged = build_statements(
        [{"key": "检索项目", "evidence": "在做检索项目"}],
        None,
        message_id="m1",
        canon=lambda k: "rag" if k == "检索项目" else k,
    )
    assert merged[0]["entity_keys"] == ["rag"]
    print("statements ok")


def test_community_lpa() -> None:
    # 两个明显分离的簇:篮球线 / 咖啡线
    nodes = ["篮球", "nba", "勇士队", "库里", "手冲咖啡", "咖啡", "v60"]
    edges = [
        ("nba", "篮球", 1.5),
        ("勇士队", "nba", 1.5),
        ("库里", "勇士队", 1.5),
        ("手冲咖啡", "咖啡", 1.5),
        ("v60", "手冲咖啡", 1.0),
    ]
    labels = label_propagation(nodes, edges)
    # LPA 之后再做连通性合并(稀疏图上 LPA 可能标签互换,合并保证同一主题线不被拆开)
    groups = {frozenset(v) for v in merge_connected_communities(group_members(labels), edges).values()}
    assert frozenset({"篮球", "nba", "勇士队", "库里"}) in groups
    assert frozenset({"手冲咖啡", "咖啡", "v60"}) in groups
    # 单个孤立节点自成社区,不报错
    assert group_members(label_propagation(["孤立"], [])) == {"孤立": ["孤立"]}
    # 标签互换造成的假拆分要被连通性合并修复
    fake_groups = {"a": ["a", "b"], "b": ["c", "d"]}
    merged = merge_connected_communities(fake_groups, [("b", "c", 1.0)])
    assert {frozenset(v) for v in merged.values()} == {frozenset({"a", "b", "c", "d"})}
    print("community lpa ok")


def test_evidence() -> None:
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    items = [
        {
            "key": "nba", "name": "NBA", "category": "体育", "status": "active", "hops": 0,
            "mention_count": 4, "since": date(2026, 7, 1), "until": None, "via": ["勇士", "库里"],
            "path": [], "reason": "seed",
        },
        {
            "key": "basketball", "name": "篮球", "category": "体育", "status": "cooled", "hops": 2,
            "mention_count": 6, "since": date(2025, 10, 1), "until": date(2026, 2, 1), "via": [],
            "path": ["NBA", "篮球"], "reason": "relation_path",
        },
    ]
    text = format_evidence(items, [{"nodes": ["NBA", "篮球"]}], graph_available=True, hops=2)
    assert "2026-07-01 至今" in text and "2025-10-01 ~ 2026-02-01" in text
    assert "已冷却" in text and "多跳路径" in text
    assert fmt_range(date(2026, 7, 1), None) == "2026-07-01 至今"
    print("evidence ok")
    _ = now


def test_extractor() -> None:
    assert should_extract("我最近迷上NBA了，勇士库里太强了")
    assert not should_extract("你好")
    assert not should_extract("帮我记住密码是 123456")
    # 问句只触发检索,不当作新的提及
    assert not should_extract("跟NBA相关的我还关注过什么?")
    assert not should_extract("我以前是不是关注过篮球?")
    assert should_extract("我最近迷上NBA了吗?")  # 带正向信号,仍抽取
    # 实体类型受控
    assert coerce_entity_type("NBA", "联赛") == "league"
    assert coerce_entity_type("库里", "球员") == "person"
    assert coerce_entity_type("NBA", "乱写类型") == "sport"  # 按分类兜底
    assert all(coerce_entity_type("X", t) == t for t in ENTITY_TYPES)

    # 接地校验:evidence 必须是原句子串
    text = "我最近迷上NBA了,勇士队库里太强了"
    assert is_grounded(text, "我最近迷上NBA了")
    assert is_grounded(text, "勇士队库里")
    assert not is_grounded(text, "勒布朗詹姆斯")
    assert not is_grounded(text, "")

    raw = (
        '```json\n{"entities":['
        '{"name":"NBA","type":"league","category":"体育","aliases":["美职篮"],'
        '"description":"美国职业篮球联赛","is_followed":true,"confidence":0.9,'
        '"evidence":"我最近迷上NBA了"},'
        '{"name":"勇士队","type":"team","category":"体育","is_followed":false,'
        '"evidence":"勇士队库里太强了"},'
        '{"name":"库里","type":"person","category":"体育","is_followed":false,'
        '"evidence":"勇士队库里太强了"},'
        '{"name":"勒布朗","type":"person","category":"体育","is_followed":false,'
        '"evidence":"勒布朗太强了"}],'
        '"relations":['
        '{"from":"NBA","to":"勇士队","type":"related","evidence":"NBA"},'
        '{"from":"勇士队","to":"库里","type":"member_of","evidence":"勇士队库里"},'
        '{"from":"NBA","to":"勒布朗","type":"related","evidence":"NBA"}]}\n```'
    )
    data = _parse_json(raw)
    result = normalize_extraction(data, text)
    names = {e["key"] for e in result["entities"]}
    assert "nba" in names and "勇士队" in names and "库里" in names
    assert "勒布朗" not in names  # 证据不在原句 → 丢弃
    assert result["entities"][0]["type"] == "league"
    assert result["entities"][0]["is_followed"] is True
    assert result["entities"][0]["since"] is not None  # "最近" 规则兜底
    assert len(result["relations"]) == 2  # 指向未抽到实体的关系被丢弃
    assert {(r["from_key"], r["to_key"], r["type"]) for r in result["relations"]} == {
        ("nba", "勇士队", "related"),
        ("勇士队", "库里", "member_of"),
    }
    empty = normalize_extraction(_parse_json("not json"), "x")
    assert empty == {"entities": [], "relations": []}
    # 互反关系去重:同一对实体只保留语义更具体的一条
    reciprocal = {
        "entities": [
            {"name": "Elixir", "type": "tech", "category": "科技", "is_followed": True,
             "evidence": "在学 Elixir"},
            {"name": "OTP", "type": "tech", "category": "科技", "is_followed": False,
             "evidence": "Elixir 的 OTP"},
        ],
        "relations": [
            {"from": "OTP", "to": "Elixir", "type": "part_of", "evidence": "Elixir 的 OTP"},
            {"from": "Elixir", "to": "OTP", "type": "related", "evidence": "Elixir 的 OTP"},
        ],
    }
    deduped = normalize_extraction(reciprocal, "在学 Elixir 的 OTP")
    assert len(deduped["relations"]) == 1
    assert deduped["relations"][0]["type"] == "part_of"
    print("extractor ok")


if __name__ == "__main__":
    test_normalize()
    test_time_and_status()
    test_scoring()
    test_query_terms()
    test_relation_terms()
    test_statements()
    test_community_lpa()
    test_evidence()
    test_extractor()
    print("ALL PASS")
