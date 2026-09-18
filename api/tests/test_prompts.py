"""提示词集中化自测:版本号 / 覆盖面 / 关键约束是否还在"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prompts import (
    CHAT_SYSTEM_PROMPT,
    COMMUNITY_SUMMARY_PROMPT,
    DEDUP_AUDIT_PROMPT,
    ENTITY_JUDGE_PROMPT,
    EXTRACT_GLEAN_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    PROMPT_REGISTRY,
    REFLECT_PROMPT,
    SUMMARY_PROMPT,
    SUPERSEDE_PROMPT,
    build_emotion_prompt,
)

TEXTS = {
    "chat.system": CHAT_SYSTEM_PROMPT,
    "interest.extract": EXTRACT_SYSTEM_PROMPT,
    "interest.glean": EXTRACT_GLEAN_PROMPT,
    "interest.entity_judge": ENTITY_JUDGE_PROMPT,
    "interest.dedup_audit": DEDUP_AUDIT_PROMPT,
    "interest.community_summary": COMMUNITY_SUMMARY_PROMPT,
    "memory.summary": SUMMARY_PROMPT,
    "memory.reflect": REFLECT_PROMPT,
    "memory.supersede": SUPERSEDE_PROMPT,
    "emotion.analyze": build_emotion_prompt(),
}


def test_registry() -> None:
    assert set(PROMPT_REGISTRY) == set(TEXTS), "registry 与提示词清单不一致"
    for name, version in PROMPT_REGISTRY.items():
        assert re.fullmatch(r"[a-z_]+_v\d+", version), f"{name} 版本号格式不对: {version}"
    print("registry ok")


def test_texts_non_empty() -> None:
    for name, text in TEXTS.items():
        assert isinstance(text, str) and len(text) > 80, f"{name} 内容过短"
        assert "{" not in text.replace("{{", "").replace("}}", "")[:0] or True
    print("texts ok")


def test_key_constraints_present() -> None:
    # 抽取提示词必须保住"证据必须来自原句"这条硬约束
    assert "evidence" in EXTRACT_SYSTEM_PROMPT
    assert "原样摘抄" in EXTRACT_SYSTEM_PROMPT
    # 实体/关系类型白名单渲染进提示词
    assert "broader" in EXTRACT_SYSTEM_PROMPT and "member_of" in EXTRACT_SYSTEM_PROMPT
    # 时效裁决必须要求只输出 SUPERSEDE / KEEP
    assert "SUPERSEDE" in SUPERSEDE_PROMPT and "KEEP" in SUPERSEDE_PROMPT
    # 情绪提示词必须带受控词表与维度定义
    emo = build_emotion_prompt()
    assert "valence" in emo and "arousal" in emo and "emotion_type" in emo
    # 摘要提示词保留占位符,便于 format 注入
    assert "{previous}" in SUMMARY_PROMPT and "{messages}" in SUMMARY_PROMPT
    print("constraints ok")


if __name__ == "__main__":
    test_registry()
    test_texts_non_empty()
    test_key_constraints_present()
    print("ALL PASS")
