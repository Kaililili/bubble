"""事实时效纯函数自测:规则判定 / 输出解析"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.memory.supersede import (
    bigram_jaccard,
    candidate_keywords,
    decide_supersede_rules,
    has_correction,
    is_supersede_answer,
    normalize_fact,
    topic_of,
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


def test_explicit_update_rules() -> None:
    """明确更正(改口)按规则直接失效;同主题不同取值交给模型裁决,不能一概删除"""
    # 秋招城市偏好:同一主题 + 明确改口 → 规则直接失效(不花模型调用)
    assert topic_of("秋招优先上海") == topic_of("现在改为优先杭州") == "求职城市"
    assert has_correction("现在改为优先杭州") and not has_correction("秋招优先上海")
    assert decide_supersede_rules("现在改为优先杭州", "秋招优先上海") == "supersede"
    # 否定/撤销也算明确更正
    assert decide_supersede_rules("我不再喜欢篮球了", "我喜欢篮球") == "supersede"
    # 两个不同爱好同属"偏好"主题:只能判为歧义交模型,绝不能被"同槽位"直接失效
    assert topic_of("我喜欢篮球") == topic_of("我喜欢电影") == "偏好"
    assert decide_supersede_rules("我喜欢电影", "我喜欢篮球") == "ambiguous"
    # 同主题但取值没变 = 重复陈述
    assert decide_supersede_rules("我秋招优先上海", "秋招优先上海") == "supersede"
    print("explicit update rules ok")


def test_candidate_keywords() -> None:
    """候选召回探测词:整句 + 主题词,保证"换了取值"的旧事实也能被找到"""
    probes = candidate_keywords("现在改为优先杭州")
    assert probes[0] == "现在改为优先杭州"
    assert "优先" in probes
    assert len(probes) == len(set(probes)) <= 6
    assert candidate_keywords("") == []
    assert candidate_keywords("我养了只猫叫咪咪") == ["我养了只猫叫咪咪"]
    print("candidate keywords ok")


def test_answer_parsing() -> None:
    assert is_supersede_answer("SUPERSEDE")
    assert is_supersede_answer("是同一件事的新版本 -> SUPERSEDE")
    assert not is_supersede_answer("KEEP")
    assert not is_supersede_answer("SUPERSEDE 还是 KEEP?两者都可能")
    assert not is_supersede_answer("")
    print("answer parsing ok")


if __name__ == "__main__":
    test_rules()
    test_explicit_update_rules()
    test_candidate_keywords()
    test_answer_parsing()
    print("ALL PASS")
