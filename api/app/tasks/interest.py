"""兴趣抽取任务:单条(兜底)与批量(缓冲合并)。"""
import logging

from celery import shared_task

from .runtime import run_async

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="interest.extract", max_retries=3, default_retry_delay=30)
def extract_interest(
    self,
    user_id: str,
    text: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    context_messages: list | None = None,
) -> int:
    """单条消息抽取(批处理关闭或兜底时使用)。"""
    from ..core.agent.interest.pipeline import extract_and_store

    try:
        return run_async(
            extract_and_store(
                user_id,
                text,
                conversation_id=conversation_id,
                message_id=message_id,
                context_messages=context_messages,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("interest.extract failed, retrying: %s", exc)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


@shared_task(bind=True, name="interest.flush_batch", max_retries=3, default_retry_delay=30)
def flush_interest_batch(self, user_id: str) -> dict:
    """把缓冲区里的消息合并成一次抽取(攒够 N 条或静默 M 秒后触发)。"""
    from ..core.agent.interest.pipeline import extract_batch_and_store
    from .batching import drain

    try:
        entries = run_async(drain(user_id))
        if not entries:
            return {"entries": 0, "written": 0}
        written = run_async(extract_batch_and_store(user_id, entries))
        return {"entries": len(entries), "written": written}
    except Exception as exc:  # noqa: BLE001
        logger.warning("interest.flush_batch failed, retrying: %s", exc)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
