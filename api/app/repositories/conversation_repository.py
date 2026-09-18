"""会话数据访问层"""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.conversation_model import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: UUID, limit: int = 100) -> list[Conversation]:
        """按更新时间倒序查询会话"""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, conversation_id: UUID, user_id: UUID) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_any(self, conversation_id: UUID) -> Conversation | None:
        """按 id 取会话(不校验 user),供后台摘要任务使用"""
        result = await self.session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def update_summary(
        self, conversation_id: UUID, summary: str, until_message_id: UUID | None
    ) -> None:
        """写入滚动摘要与摘要游标(游标指向已摘要的最后一条消息)"""
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(
                summary=summary,
                summary_until_message_id=until_message_id,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.commit()

    async def create(self, user_id: UUID, title: str = "新对话") -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        self.session.add(conv)
        await self.session.commit()
        await self.session.refresh(conv)
        return conv

    async def update_title(self, conversation_id: UUID, title: str) -> None:
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(
                title=title, updated_at=datetime.now(timezone.utc)
            )
        )
        await self.session.commit()

    async def touch(self, conversation_id: UUID) -> None:
        """更新会话时间戳(用于排序)"""
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(
                updated_at=datetime.now(timezone.utc)
            )
        )
        await self.session.commit()

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.commit()
