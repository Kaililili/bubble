"""事实时效纯函数自测:规则判定 / 输出解析"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.memory.supersede import (
    bigram_jaccard,
    decide_supersede_rules,
    is_supersede_answer,
    normalize_fact,
)


def test_rules() -> None:
    assert normalize_fact(" 我 住在 上海 ") == "我住在上海"
    assert bigram_jaccard("我住在上海", "我住在上海") == 1.0
    assert bigram_jaccard("我住在上海", "我在学 Rust") < 0.2
    # 同一槽位换值:字面几乎不重合,相似度抓不到,必须靠槽位规则
    assert bigram_jaccard("我住在上海", "我搬到杭州了") < 0.2
    assert decide_supersede_rules("我搬到杭州了", "我住在上海") == "ambiguous"
    assert decide_supersede_rules("我换工作了", "我在腾讯工作") == "ambiguous"
    assert decide_supersede_rules("我住在上海", "我住在上海") == "supersede"
    assert decide_supersede_rules("我住在上海浦江镇", "我住在上海") == "supersede"
    assert decide_supersede_rules("我养了只猫叫咪咪", "我在学 Rust") == "keep"
    print("supersede rules ok")


def test_answer_parsing() -> None:
    assert is_supersede_answer("SUPERSEDE")
    assert is_supersede_answer("是同一件事的新版本 -> SUPERSEDE")
    assert not is_supersede_answer("KEEP")
    assert not is_supersede_answer("SUPERSEDE 还是 KEEP?两者都可能")
    assert not is_supersede_answer("")
    print("answer parsing ok")


if __name__ == "__main__":
    test_rules()
    test_answer_parsing()
    print("ALL PASS")
