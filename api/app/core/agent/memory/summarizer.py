"""会话滚动摘要:把超窗口的早期对话增量压成摘要,供上下文注入。

- 只压尚未摘要的溢出部分,已有摘要作为上文一起带上,避免每次全量重算
- 独立 session、失败不影响聊天(与兴趣/情绪抽取同款后台任务)
"""
import logging

from .context import (
    RECENT_WINDOW,
    SUMMARY_MAX_CHARS,
    pending_overflow,
    render_messages,
    should_summarize,
)

logger = logging.getLogger(__name__)
from ....prompts.memory import SUMMARY_PROMPT



async def summarize_conversation(session, conversation_id, model=None) -> str | None:
    """生成/更新会话摘要;未触发或失败返回 None"""
    from app.repositories.conversation_repository import ConversationRepository
    from app.repositories.message_repository import MessageRepository

    conv_repo = ConversationRepository(session)
    conversation = await conv_repo.get_by_id_any(conversation_id)
    if conversation is None:
        return None

    messages = await MessageRepository(session).list_all(conversation_id)
    pending = pending_overflow(messages, conversation.summary_until_message_id, RECENT_WINDOW)
    if not should_summarize(pending):
        return None

    if model is None:
        from app.core.llm.client import build_chat_model
        from app.core.llm.resolver import get_default_config

        config = await get_default_config(session, conversation.user_id, "chat")
        model = build_chat_model(config, streaming=False, temperature=0.2)

    prompt = SUMMARY_PROMPT.format(
        previous=(conversation.summary or "(无)")[:SUMMARY_MAX_CHARS],
        messages=render_messages(pending),
    )
    try:
        from langchain_core.messages import HumanMessage

        result = await model.ainvoke([HumanMessage(content=prompt)])
        content = getattr(result, "content", result)
        summary = (content if isinstance(content, str) else str(content)).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("conversation summary failed: %s", e)
        return None
    if not summary:
        return None

    await conv_repo.update_summary(
        conversation_id,
        summary=summary[:SUMMARY_MAX_CHARS],
        until_message_id=getattr(pending[-1], "id", None),
    )
    logger.info("conversation %s summarized: %d messages", conversation_id, len(pending))
    return summary


async def run_summary_task(conversation_id) -> None:
    """后台入口:独立 session,异常只记日志"""
    from app.db.postgres import async_session

    try:
        async with async_session() as session:
            await summarize_conversation(session, conversation_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("conversation summary task failed: %s", e)
