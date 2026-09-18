"""消息数据访问层"""
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.conversation_model import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_conversation(self, conversation_id: UUID, limit: int = 200) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, conversation_id: UUID, limit: int = 1000) -> list[Message]:
        """全量消息(时间正序),供会话摘要使用;带上限保护避免超长会话拖垮内存"""
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent(self, conversation_id: UUID, limit: int = 40) -> list[Message]:
        """最近 limit 条消息(按时间正序返回)。

        注意:不能用 `asc + limit` —— 那样拿到的是最早的 N 条,长会话会完全看不到新消息。
        """
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return rows

    async def count(self, conversation_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        return int(result.scalar_one() or 0)

    async def create(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        tool_calls: dict | None = None,
        metadata: dict | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            meta=metadata,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg
