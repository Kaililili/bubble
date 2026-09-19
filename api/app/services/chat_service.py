"""聊天业务:历史构建 → Agent 编排流式生成 → 持久化"""
import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.agent.orchestrator import run_agent
from ..core.agent.intent import detect_memory_intent
from ..prompts.chat import CHAT_SYSTEM_PROMPT as SYSTEM_PROMPT
from ..core.agent.prompt_renderer import render_tools_prompt
from ..core.agent.tools import build_enabled_tools
from ..core.exceptions import AppException
from ..core.llm.client import build_chat_model
from ..core.llm.resolver import get_default_config
from ..core.security import sanitize_credential_text
from ..repositories.conversation_repository import ConversationRepository
from ..repositories.message_repository import MessageRepository

logger = logging.getLogger(__name__)


# 用户背景注入 system prompt 的长度护栏(约 800 token,防止背景撑爆上下文)
MAX_PROFILE_CHARS = 1600


class ChatService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self._pending_intent = None
        self._pending_user_id = None
        self._pending_user_text = ""
        self._pending_message_id = None
        self._pending_context: list[str] = []

    async def _load_profile_block(self, user_id: UUID) -> str:
        """加载用户背景,拼成固定格式文本;超长按 importance 从高到低截断"""
        from ..repositories.memory_repository import UserProfileRepository

        profiles = await UserProfileRepository(self.session).list_by_user(user_id)
        if not profiles:
            return ""
        lines = ["[用户背景]"]
        total = 0
        for p in profiles:
            line = f"{p.key}: {p.value}"
            total += len(line) + 1
            if total > MAX_PROFILE_CHARS:
                break
            lines.append(line)
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    async def prepare(self, conversation_id: UUID, user_id: UUID, content: str):
        """校验会话、持久化用户消息、构建模型/工具/历史。

        在返回 StreamingResponse 之前完成,校验失败直接走统一异常处理。
        """
        conv = await self.conversations.get_by_id(conversation_id, user_id)
        if not conv:
            raise AppException(code=404, message="会话不存在")

        config = await get_default_config(self.session, user_id, "chat")
        model = build_chat_model(config)
        tools = await build_enabled_tools(self.session, user_id, conversation_id)
        supports = bool(config.supports_function_call)

        # 先读历史(不含当前消息):只取最近一屏,更早的部分由滚动摘要代替
        from ..core.agent.memory.context import RECENT_WINDOW, format_summary_block

        rows = await self.messages.list_recent(conversation_id, limit=RECENT_WINDOW)
        from ..core.agent.interest.context_window import CONTEXT_MESSAGES

        self._pending_context = [
            ("用户: " if r.role == "user" else "助手: ") + (r.content or "")
            for r in rows[-CONTEXT_MESSAGES:]
        ]
        system_prompt = SYSTEM_PROMPT
        # ReAct 路径需要把工具说明渲染进系统提示词
        if not supports:
            tools_text = render_tools_prompt(tools)
            if tools_text:
                system_prompt = SYSTEM_PROMPT + "\n\n" + tools_text
        # 注入用户背景(常驻层)
        profile_block = await self._load_profile_block(user_id)
        if profile_block:
            system_prompt = system_prompt + "\n\n" + profile_block
        # 会话早期摘要:长会话防失忆,并把上下文 token 从 O(轮数) 压到 O(1)
        if conv.summary:
            total = await self.messages.count(conversation_id)
            older = max(0, total - len(rows))
            if older > 0:
                system_prompt = system_prompt + "\n\n" + format_summary_block(
                    conv.summary, older
                )
        # 情绪档案(有记录才注入);负面信号时附带相关记忆
        emotion_block = await self._load_emotion_block(user_id, content)
        if emotion_block:
            system_prompt = system_prompt + "\n\n" + emotion_block
        insight_block = await self._load_insight_block(user_id)
        if insight_block:
            system_prompt = system_prompt + "\n\n" + insight_block

        # 历史消息用存储内容(已脱敏),当前消息用原文(让模型读到真实值以调用工具)
        history = [SystemMessage(content=system_prompt)]
        for row in rows:
            if row.role == "user":
                history.append(HumanMessage(content=row.content))
            elif row.role == "assistant":
                history.append(AIMessage(content=row.content))
        history.append(HumanMessage(content=content))

        # 持久化脱敏后的用户消息(历史中不保留凭证明文)
        safe_content = sanitize_credential_text(content)
        user_message = await self.messages.create(conversation_id, role="user", content=safe_content)
        self._pending_message_id = getattr(user_message, "id", None)
        if conv.title == "新对话":
            await self.conversations.update_title(conversation_id, title=safe_content[:20] or "新对话")

        # 意图检测(供 stream 结束时兜底:模型没调工具则自动补调)
        self._pending_intent = detect_memory_intent(content)
        self._pending_user_id = user_id
        self._pending_user_text = content

        return model, tools, supports, history, conversation_id

    async def _schedule_interest_extraction(self, conversation_id: UUID) -> None:
        """回复结束后派发兴趣抽取:投递到 Celery 队列,由 worker 消费(进程重启不丢)"""
        from ..tasks import dispatch

        await dispatch.enqueue_interest(
            self._pending_user_id,
            self._pending_user_text,
            conversation_id,
            self._pending_message_id,
            self._pending_context,
        )

    def _schedule_conversation_summary(self, conversation_id: UUID) -> None:
        """回复结束后派发会话摘要 + 洞察刷新(摘要未达阈值时内部直接返回)"""
        from ..tasks import dispatch

        dispatch.enqueue_summary(conversation_id)
        dispatch.enqueue_insight(self._pending_user_id)

    async def _load_emotion_block(self, user_id: UUID, content: str) -> str:
        """情绪档案(常驻);负面信号时追加相关记忆,失败一律降级为空"""
        from ..core.agent.emotion.aggregator import aggregate_profile, format_profile_block
        from ..core.agent.emotion.ontology import has_emotion_hint
        from ..repositories.emotion_repository import EmotionRepository

        try:
            rows = await EmotionRepository(self.session).list_recent(user_id, days=7, limit=20)
        except Exception as e:  # noqa: BLE001
            logger.warning("load emotion profile failed: %s", e)
            return ""
        if not rows:
            return ""
        profile = aggregate_profile(rows)
        negative_now = has_emotion_hint(content or "")
        block = format_profile_block(profile, negative_now=negative_now)
        if not block:
            return ""
        if negative_now or (profile.trend == "down" and profile.negative_ratio >= 0.5):
            memory_block = await self._load_related_memory_block(user_id, content)
            if memory_block:
                block = f"{block}\n{memory_block}"
        return block

    async def _load_insight_block(self, user_id: UUID) -> str:
        """洞察层常驻注入:读不到或未生成时返回空串,不影响对话"""
        try:
            from ..core.agent.memory.insight import load_insight_block

            return await load_insight_block(self.session, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load insight block failed: %s", exc)
            return ""

    async def _load_related_memory_block(self, user_id: UUID, content: str) -> str:
        """负面情绪时的相关记忆检索(与 recall 工具同一条融合链路,失败返回空)"""
        from ..core.agent.memory.retrieval import search_memories

        try:
            rows = await search_memories(self.session, user_id, content or "", limit=3)
        except Exception as e:  # noqa: BLE001
            logger.warning("load related memory failed: %s", e)
            return ""
        lines = [f"- [{r.type}] {r.content}" for r in rows if (r.content or "").strip()]
        if not lines:
            return ""
        return "[相关记忆]\n" + "\n".join(lines[:3])

    def _schedule_emotion_analysis(self, conversation_id: UUID) -> None:
        """回复结束后派发情绪分析:与兴趣同款,投递到 Celery 队列由 worker 消费"""
        from ..tasks import dispatch

        dispatch.enqueue_emotion(
            self._pending_user_id,
            self._pending_user_text,
            conversation_id,
            self._pending_message_id,
            self._interest_tasks,
        )

    async def _auto_save_memory(self, intent, tool_events: list) -> str:
        """意图兜底:模型未调写入工具时,按检测到的槽位自动保存记忆。"""
        from ..core.agent.tools.base import ToolContext
        from ..core.agent.tools.builtin.memory_tools import remember

        if not intent.value:
            return "⚠️ 没能自动保存:没有提取到要保存的真实内容,请再说一次完整的信息。"

        parts = [p for p in (intent.key, intent.type_word, intent.value) if p]
        content = " ".join(parts)
        ctx = ToolContext(self.session, self._pending_user_id)
        result = await remember(ctx, content=content, type=intent.type)
        ok = result.startswith(("已记住", "已更新"))
        tool_events.append(
            {
                "tool": "remember",
                "query": "",
                "status": "success" if ok else "error",
                "text": result,
                "latency_ms": 0,
            }
        )
        return f"✅ 已自动保存:{result}" if ok else f"⚠️ 未能保存:{result}"

    async def stream(
        self, model, tools, supports: bool, history, conversation_id: UUID
    ) -> AsyncGenerator[str, None]:
        """运行 Agent 编排,把事件通过 SSE 透传;结束时持久化助手回复"""
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict):
            await queue.put(event)

        task = asyncio.create_task(run_agent(model, tools, history, supports, emit))
        full_text = ""
        tool_events = []
        error_message = ""
        error_sent = False
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    logger.warning("Agent 流式输出超时")
                    break
                if event["type"] == "token":
                    full_text += event.get("text", "")
                elif event["type"] == "final":
                    break
                elif event["type"] == "error":
                    error_message = event.get("message", "Agent 运行出错")
                    error_sent = True
                elif event["type"] == "tool_result":
                    tool_events.append(
                        {
                            "tool": event.get("tool", ""),
                            "query": event.get("query", ""),
                            "status": event.get("status", ""),
                            "text": event.get("text", ""),
                            "full_text": event.get("full_text") or event.get("text", ""),
                            "latency_ms": event.get("latency_ms"),
                        }
                    )
                elif event["type"] == "tool_approval_required":
                    # 敏感工具待确认:持久化进事件,前端渲染审批卡片(历史可恢复)
                    tool_events.append(
                        {
                            "type": "approval",
                            "approval_id": event.get("approval_id"),
                            "tool": event.get("tool", ""),
                            "args": event.get("args"),
                            "status": "pending",
                        }
                    )
                yield json.dumps(event, ensure_ascii=False)
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

            # 意图兜底:检测到"记住/更换记忆"但模型没调写入工具时,自动补调 remember
            if self._pending_intent and not any(
                e.get("tool") in ("remember", "save_profile") for e in tool_events
            ):
                fallback_text = await self._auto_save_memory(self._pending_intent, tool_events)
                if fallback_text:
                    full_text = (full_text + "\n\n" + fallback_text).strip() if full_text else fallback_text

            if full_text:
                await self.messages.create(
                    conversation_id,
                    role="assistant",
                    content=full_text,
                    tool_calls={"events": tool_events} if tool_events else None,
                )
            await self.conversations.touch(conversation_id)
            await self._schedule_interest_extraction(conversation_id)
            self._schedule_emotion_analysis(conversation_id)
            self._schedule_conversation_summary(conversation_id)

        if error_message and not error_sent:
            yield json.dumps({"type": "error", "message": error_message}, ensure_ascii=False)
        yield json.dumps({"type": "final", "text": full_text}, ensure_ascii=False)
