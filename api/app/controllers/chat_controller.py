"""会话与聊天 API 路由"""
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_user
from ..core.exceptions import AppException
from ..core.response import success
from ..db import get_session
from ..models.user_model import User
from ..repositories.conversation_repository import ConversationRepository
from ..repositories.message_repository import MessageRepository
from ..schemas.chat_schema import (
    ChatRequest,
    ConversationCreateRequest,
    ConversationResponse,
    MessageResponse,
)
from ..services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    items = await repo.list_by_user(current_user.id)
    return success(data=[ConversationResponse.model_validate(i).model_dump() for i in items])


@router.post("")
async def create_conversation(
    body: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    conv = await repo.create(current_user.id, title=body.title or "新对话")
    return success(data=ConversationResponse.model_validate(conv).model_dump())


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    conv = await repo.get_by_id(conversation_id, current_user.id)
    if not conv:
        raise AppException(code=404, message="会话不存在")
    await repo.delete(conv)
    return success(data=None)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepository(session)
    conv = await repo.get_by_id(conversation_id, current_user.id)
    if not conv:
        raise AppException(code=404, message="会话不存在")
    msgs = await MessageRepository(session).list_by_conversation(conversation_id)
    return success(data=[MessageResponse.model_validate(m).model_dump() for m in msgs])


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """SSE 流式聊天"""
    svc = ChatService(session)
    model, tools, supports, history, cid = await svc.prepare(conversation_id, current_user.id, body.content)

    async def event_stream():
        async for payload in svc.stream(model, tools, supports, history, cid):
            yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
