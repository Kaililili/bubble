"""情绪分析任务。"""
import logging

from celery import shared_task

from .runtime import run_async

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="emotion.analyze", max_retries=3, default_retry_delay=30)
def analyze_emotion(self, user_id: str, text: str, conversation_id: str | None = None,
                    message_id: str | None = None) -> int:
    from ..core.agent.emotion.pipeline import analyze_and_store

    try:
        return run_async(analyze_and_store(user_id, text, conversation_id, message_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("emotion.analyze failed, retrying: %s", exc)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
