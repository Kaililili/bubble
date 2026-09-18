"""记忆系统纯函数自测:融合打分 / 上下文窗口 / 滚动摘要切分。"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.memory.context import (
    RECENT_WINDOW,
    format_summary_block,
    pending_overflow,
    render_messages,
    should_summarize,
    split_window,
)
from app.core.agent.memory.ranking import fuse_score, importance_norm, recency_score
from app.core.agent.memory.insight import (
    format_insight_block,
    normalize_insight,
    should_refresh,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def _msg(index: int, role: str = "user", content: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=f"m{index}", role=role, content=content or f"msg{index}")


def test_ranking() -> None:
    assert importance_norm(0) == 0.0
    assert importance_norm(10) == 1.0
    assert importance_norm(20) == 1.0
    assert importance_norm(None) == 0.0
    assert abs(recency_score(NOW, now=NOW) - 1.0) < 1e-9
    assert abs(recency_score(NOW - timedelta(days=30), now=NOW) - 0.5) < 1e-6
    assert recency_score(None, now=NOW) == 0.0
    assert fuse_score(0.8, 9, NOW, now=NOW) > fuse_score(0.8, 1, NOW, now=NOW)
    assert fuse_score(0.8, 5, NOW, now=NOW) > fuse_score(
        0.8, 5, NOW - timedelta(days=180), now=NOW
    )
    assert fuse_score(0.95, 0, NOW - timedelta(days=365), now=NOW) > fuse_score(
        0.3, 10, NOW, now=NOW
    )
    assert fuse_score(None, 10, NOW, now=NOW) > 0
    print("ranking ok")


def test_context_window() -> None:
    messages = [_msg(i) for i in range(1, 101)]
    older, recent = split_window(messages, window=40)
    assert len(recent) == 40 and len(older) == 60
    assert recent[0].id == "m61" and recent[-1].id == "m100"
    assert split_window(messages[:10], window=40) == ([], messages[:10])
    print("context window ok")


def test_summary_trigger() -> None:
    messages = [_msg(i) for i in range(1, 101)]
    pending = pending_overflow(messages, None, window=40)
    assert len(pending) == 60 and pending[0].id == "m1"
    assert should_summarize(pending, trigger=16)
    pending = pending_overflow(messages, "m40", window=40)
    assert len(pending) == 20 and pending[0].id == "m41" and pending[-1].id == "m60"
    assert len(pending_overflow(messages, "m999", window=40)) == 60
    assert not should_summarize(pending_overflow([_msg(i) for i in range(1, 46)], None, 40))
    print("summary trigger ok")


def test_render_and_block() -> None:
    text = render_messages([_msg(1, "user", "wo jiao cheng yuan"), _msg(2, "assistant", "hao")])
    assert text.startswith("用户: ") and "助手: " in text
    long_text = render_messages(
        [_msg(1, "user", "old" * 200), _msg(2, "user", "new" * 200)], char_budget=120
    )
    assert "new" in long_text and "old" not in long_text
    block = format_summary_block("用户在学 Rust,准备找后端岗", 12)
    assert "12" in block and "Rust" in block
    assert format_summary_block("", 3) == ""
    assert format_summary_block(None, 3) == ""
    assert RECENT_WINDOW == 40
    print("render + block ok")


if __name__ == "__main__":
    test_ranking()
    test_context_window()
    test_summary_trigger()
    test_render_and_block()
    print("ALL PASS")
