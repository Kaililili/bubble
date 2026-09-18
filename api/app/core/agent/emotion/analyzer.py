"""情绪分析器:规则预筛 + LLM 结构化抽取 + 接地/一致性校验。

失败(LLM 异常/JSON 解析失败)返回 None,由上层丢弃,不写垃圾记录。
"""
import json
import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from .ontology import (
    COMMAND_HINTS,
    DEFAULT_EMOTION,
    clamp_arousal,
    clamp_intensity,
    clamp_valence,
    has_emotion_hint,
    normalize_emotion,
    reference_coords,
)
from .prompt import build_emotion_prompt

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
_MIN_LEN = 4
_QUESTION_RE = re.compile(r"[?？]|吗\s*$|什么|哪些|怎么|为什么")
_PUNCT_RE = re.compile(r"[\s,，。.;；:：!！?？\"'“”‘’()（）\[\]【】\-—_/]+")


@dataclass
class EmotionResult:
    emotion_type: str
    intensity: float
    valence: float
    arousal: float
    keywords: list[str] = field(default_factory=list)
    trigger: str | None = None
    summary: str | None = None


def should_analyze(text: str) -> bool:
    """保守预筛:只跳过"纯指令/查询且无任何情绪词"的消息,尽量不漏情绪。

    (情绪是弱信号,规则容易漏;这里只挡明显无信息量的指令类消息,其余交给模型。)
    """
    value = (text or "").strip()
    if len(value) < _MIN_LEN:
        return False
    if has_emotion_hint(value):
        return True
    if any(h in value for h in COMMAND_HINTS) or _QUESTION_RE.search(value):
        return False
    return True


def _normalized(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").lower())


def is_grounded(raw_text: str, phrase: str | None) -> bool:
    """接地校验:短语(去空白标点后)必须能在原句里找到"""
    target = _normalized(phrase or "")
    return bool(target) and target in _normalized(raw_text)


def _coerce_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("emotion JSON parse failed")
        return {}


def normalize_result(data: dict, raw_text: str) -> EmotionResult:
    """把 LLM 输出规范化为 EmotionResult:词表收敛 + 维度 clamp + 接地 + 一致性校验"""
    emotion = normalize_emotion(data.get("emotion_type") if isinstance(data, dict) else None)
    ref_v, ref_a = reference_coords(emotion)
    intensity = clamp_intensity(_coerce_float(data.get("intensity"), 0.0))
    valence = clamp_valence(_coerce_float(data.get("valence"), ref_v))
    arousal = clamp_arousal(_coerce_float(data.get("arousal"), ref_a))
    # 一致性校验:维度与主情绪参考值偏差过大时以词表为准(防"喜悦 + 强负效价"这类自相矛盾)
    if abs(valence - ref_v) > 0.6:
        logger.info("emotion valence inconsistent with %s, use reference", emotion)
        valence = ref_v
    if abs(arousal - ref_a) > 0.6:
        logger.info("emotion arousal inconsistent with %s, use reference", emotion)
        arousal = ref_a

    keywords: list[str] = []
    for item in (data.get("keywords") or [])[:5]:
        word = str(item).strip()[:32]
        if word and is_grounded(raw_text, word) and word not in keywords:
            keywords.append(word)

    trigger = data.get("trigger")
    trigger = str(trigger).strip()[:255] or None if isinstance(trigger, str) else None
    if trigger and not is_grounded(raw_text, trigger):
        trigger = None  # 原句里没有 → 模型编造的触发事件,丢弃

    summary = data.get("summary")
    summary = str(summary).strip()[:500] if isinstance(summary, str) and str(summary).strip() else None

    return EmotionResult(
        emotion_type=emotion,
        intensity=intensity,
        valence=valence,
        arousal=arousal,
        keywords=keywords,
        trigger=trigger,
        summary=summary,
    )


def _content_to_text(content) -> str:
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


async def analyze_emotion(model, text: str) -> EmotionResult | None:
    """分析单段用户文本的情绪;失败返回 None(由上层丢弃)"""
    clean = (text or "").strip()
    if not clean:
        return None
    messages = [SystemMessage(content=build_emotion_prompt()), HumanMessage(content=clean[:2000])]
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await model.ainvoke(messages)
        except Exception as e:  # noqa: BLE001
            logger.warning("emotion LLM call failed (attempt %s): %s", attempt + 1, e)
            continue
        data = _parse_json(_content_to_text(response.content))
        if not data:
            continue
        result = normalize_result(data, clean)
        if result.emotion_type == DEFAULT_EMOTION and result.intensity > 0.8:
            # 主情绪缺失却给了高强度的自相矛盾输出 → 视为解析失败重试
            continue
        return result
    return None
