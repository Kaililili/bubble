"""情绪模块纯函数自测:词表归一 / 预筛 / 接地校验 / 画像聚合 / 分桶 / 词云

用法(api/ 目录下): ..\\.venv\\Scripts\\python.exe tests\\test_emotion_units.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.emotion.aggregator import (
    aggregate_profile,
    bucket_history,
    build_wordcloud,
    emotion_distribution,
    format_profile_block,
)
from app.core.agent.emotion.analyzer import (
    is_grounded,
    normalize_result,
    should_analyze,
)
from app.core.agent.emotion.ontology import (
    clamp_arousal,
    clamp_intensity,
    clamp_valence,
    has_emotion_hint,
    is_negative,
    normalize_emotion,
    reference_coords,
)

NOW = datetime(2026, 9, 14, 20, 0, tzinfo=timezone.utc)


def rec(days_ago: float, emotion: str, valence: float, arousal=0.5, intensity=0.6,
        keywords=None, trigger=None):
    return SimpleNamespace(
        created_at=NOW - timedelta(days=days_ago),
        emotion_type=emotion,
        valence=valence,
        arousal=arousal,
        intensity=intensity,
        keywords=keywords or [],
        trigger=trigger,
    )


def test_ontology() -> None:
    assert normalize_emotion("喜悦") == "喜悦"
    assert normalize_emotion("随便写的") == "中性"
    assert reference_coords("焦虑") == (-0.5, 0.7)
    assert clamp_valence(3) == 1.0 and clamp_valence(-3) == -1.0
    assert clamp_arousal(-1) == 0.0 and clamp_arousal(9) == 1.0
    assert clamp_intensity(5) == 1.0
    assert is_negative("焦虑") and not is_negative("喜悦")
    assert has_emotion_hint("今天真的好烦") and not has_emotion_hint("帮我查一下天气")
    print("ontology ok")


def test_prefilter() -> None:
    assert not should_analyze("帮我查一下明天北京的天气")
    assert not should_analyze("明天天气怎么样?")
    assert not should_analyze("好的")           # 太短
    assert should_analyze("今天组会又被导师说了,好烦")
    assert should_analyze("为什么我总是这么累")  # 问句但有情绪词
    assert should_analyze("我周末去看了场电影")  # 普通叙述 → 交给模型(中性会被阈值过滤)
    print("prefilter ok")


def test_grounding_and_normalize() -> None:
    text = "今天组会又被导师说了,好烦,感觉做什么都不对"
    assert is_grounded(text, "组会")
    assert is_grounded(text, "被导师说了")
    assert not is_grounded(text, "项目延期")

    data = {
        "emotion_type": "焦虑",
        "intensity": 1.7,            # 越界 → clamp 到 1.0
        "valence": -0.6,
        "arousal": 0.7,
        "keywords": ["组会", "导师", "项目延期"],  # 最后一个未接地 → 丢弃
        "trigger": "项目延期",        # 未接地 → None
        "summary": "用户因组会被批评而焦虑",
    }
    result = normalize_result(data, text)
    assert result.emotion_type == "焦虑"
    assert result.intensity == 1.0
    assert result.keywords == ["组会", "导师"]
    assert result.trigger is None

    # 一致性校验:喜悦却给强负效价 → 以词表参考值为准
    inconsistent = normalize_result(
        {"emotion_type": "喜悦", "intensity": 0.8, "valence": -0.9, "arousal": 0.7,
         "keywords": ["开心"], "trigger": None, "summary": None},
        "今天很开心",
    )
    assert inconsistent.valence == 0.8
    # 词表外情绪 → 中性
    assert normalize_result({"emotion_type": "暴躁"}, "随便").emotion_type == "中性"
    print("grounding/normalize ok")


def test_aggregate_profile() -> None:
    records = [
        rec(6, "平静", 0.2, trigger=None),
        rec(5, "焦虑", -0.5, intensity=0.8, trigger="组会"),
        rec(4, "焦虑", -0.6, intensity=0.9, trigger="项目延期"),
        rec(3, "疲惫", -0.3, trigger="组会"),
        rec(2, "平静", 0.2),
        rec(1, "焦虑", -0.7, intensity=0.9, trigger="项目延期"),
    ]
    agg = aggregate_profile(records)
    assert agg.sample_count == 6
    assert agg.dominant_emotion == "焦虑"
    assert agg.avg_valence < 0
    assert agg.trend in ("up", "flat", "down")
    assert agg.negative_ratio > 0.5
    assert agg.recent_triggers[0] == "项目延期"

    block = format_profile_block(agg, negative_now=True)
    assert "[情绪档案]" in block and "共情" in block
    assert format_profile_block(aggregate_profile([])) == ""
    print("aggregate ok")


def test_history_and_wordcloud() -> None:
    records = [
        rec(0, "焦虑", -0.6, keywords=["组会", "导师"], trigger="组会"),
        rec(0.1, "平静", 0.2, keywords=["组会"]),
        rec(8, "喜悦", 0.8, keywords=["offer"]),
        rec(40, "悲伤", -0.7, keywords=["失恋"]),
    ]
    daily = bucket_history(records, "day")
    assert [p["bucket"] for p in daily] == sorted(p["bucket"] for p in daily)
    assert sum(p["count"] for p in daily) == 4
    assert any(p["dominant_emotion"] == "焦虑" for p in daily)
    weekly = bucket_history(records, "week")
    assert sum(p["count"] for p in weekly) == 4
    monthly = bucket_history(records, "month")
    assert len(monthly) == 2  # 2026-09 与 2026-08

    cloud = build_wordcloud(records)
    top = cloud[0]
    assert top["word"] == "组会" and top["count"] == 2
    assert "valence" in top

    dist = emotion_distribution(records)
    polarities = [d["polarity"] for d in dist]
    assert polarities == sorted(polarities)
    print("history/wordcloud ok")


if __name__ == "__main__":
    test_ontology()
    test_prefilter()
    test_grounding_and_normalize()
    test_aggregate_profile()
    test_history_and_wordcloud()
    print("ALL PASS")
