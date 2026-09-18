"""洞察层纯函数自测:触发节流 / 清洗 / 注入块"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.memory.insight import (
    format_insight_block,
    normalize_insight,
    should_refresh,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def test_insight_layer() -> None:
    assert not should_refresh(3, None)
    assert should_refresh(5, None)
    assert not should_refresh(9, NOW - timedelta(days=1), now=NOW)
    assert should_refresh(9, NOW - timedelta(days=4), now=NOW)
    assert normalize_insight({"theme": "", "content": "足够长的内容文本"}) is None
    assert normalize_insight({"theme": "职业", "content": "短"}) is None
    item = normalize_insight(
        {
            "theme": "职业发展",
            "content": "用户在做检索方向的工程项目",
            "confidence": 3,
            "importance": 99,
        }
    )
    assert item["confidence"] == 1.0 and item["importance"] == 10
    block = format_insight_block([item])
    assert "职业发展" in block and "整体理解" in block
    assert format_insight_block([]) == ""
    print("insight layer ok")


def test_context_window() -> None:
    from app.core.agent.interest.context_window import build_context_block

    assert build_context_block([]) == ""
    block = build_context_block(["我喜欢勇士队", "  他  三分太强了  "])
    assert "勇士队" in block and "三分" in block
    assert "不能作为证据" in block
    long_text = "长" * 500
    assert len(build_context_block([long_text])) < 400
    limited = build_context_block(["a1", "a2", "a3", "a4", "a5"], limit=2)
    assert "a1" not in limited and "a4" in limited and "a5" in limited
    print("context window ok")


if __name__ == "__main__":
    test_insight_layer()
    test_context_window()
    print("ALL PASS")
