"""集中管理所有提示词。

每个领域一个模块,模块顶部声明 `VERSION`;`PROMPT_REGISTRY` 汇总"提示词名 -> 版本",
便于在调用日志里记录版本、必要时回滚或做 A/B。
"""

from .chat import CHAT_SYSTEM_PROMPT, VERSION as CHAT_VERSION
from .emotion import build_emotion_prompt, VERSION as EMOTION_VERSION
from .interest import (
    COMMUNITY_SUMMARY_PROMPT,
    DEDUP_AUDIT_PROMPT,
    ENTITY_JUDGE_PROMPT,
    EXTRACT_GLEAN_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    VERSION as INTEREST_VERSION,
)
from .ontology import ENTITY_TYPES, RELATION_TYPES
from .memory import (
    REFLECT_PROMPT,
    SUMMARY_PROMPT,
    SUPERSEDE_PROMPT,
    VERSION as MEMORY_VERSION,
)

PROMPT_REGISTRY: dict[str, str] = {
    "chat.system": CHAT_VERSION,
    "interest.extract": INTEREST_VERSION,
    "interest.glean": INTEREST_VERSION,
    "interest.entity_judge": INTEREST_VERSION,
    "interest.dedup_audit": INTEREST_VERSION,
    "interest.community_summary": INTEREST_VERSION,
    "emotion.analyze": EMOTION_VERSION,
    "memory.summary": MEMORY_VERSION,
    "memory.reflect": MEMORY_VERSION,
    "memory.supersede": MEMORY_VERSION,
}

__all__ = [
    "CHAT_SYSTEM_PROMPT",
    "COMMUNITY_SUMMARY_PROMPT",
    "DEDUP_AUDIT_PROMPT",
    "ENTITY_JUDGE_PROMPT",
    "EXTRACT_GLEAN_PROMPT",
    "EXTRACT_SYSTEM_PROMPT",
    "PROMPT_REGISTRY",
    "REFLECT_PROMPT",
    "SUMMARY_PROMPT",
    "SUPERSEDE_PROMPT",
    "build_emotion_prompt",
]
