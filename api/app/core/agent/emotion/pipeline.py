"""情绪分析后台任务:回复结束后异步执行,失败不影响聊天"""
import asyncio
import logging

from ....config import settings
from ....db.postgres import async_session
from .analyzer import analyze_emotion, should_analyze

logger = logging.getLogger(__name__)

ANALYZE_TIMEOUT = 40


async def analyze_and_store(
    user_id,
    text: str,
    conversation_id=None,
    message_id=None,
    occurred_at=None,
) -> int:
    """分析一条用户消息的情绪并入库;返回写入条数(0 = 跳过/失败)"""
    if not should_analyze(text):
        logger.debug("emotion prefiltered (pure command/query): user=%s", user_id)
        return 0
    try:
        async with async_session() as session:
            from ....core.llm.client import build_chat_model
            from ....core.llm.resolver import get_default_config
            from ....core.security import sanitize_credential_text
            from ....repositories.emotion_repository import EmotionRepository

            try:
                config = await get_default_config(session, user_id, "chat")
            except Exception:  # noqa: BLE001
                logger.info("emotion analysis skipped (no chat model): user=%s", user_id)
                return 0
            model = build_chat_model(config, streaming=False, temperature=0)
            result = await asyncio.wait_for(analyze_emotion(model, text), timeout=ANALYZE_TIMEOUT)
            if result is None:
                return 0
            if result.intensity < settings.emotion_min_intensity:
                logger.debug(
                    "emotion below threshold, dropped: user=%s intensity=%.2f",
                    user_id,
                    result.intensity,
                )
                return 0
            await EmotionRepository(session).create(
                user_id=user_id,
                emotion_type=result.emotion_type,
                intensity=result.intensity,
                valence=result.valence,
                arousal=result.arousal,
                keywords=result.keywords,
                trigger=result.trigger,
                summary=result.summary,
                evidence=sanitize_credential_text(text),
                source="llm",
                conversation_id=conversation_id,
                message_id=message_id,
                created_at=occurred_at,
            )
            return 1
    except asyncio.TimeoutError:
        logger.warning("emotion analysis timeout: user=%s", user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("emotion analysis failed: %s", e)
    return 0
