"""情绪数据访问层:情绪快照的写入与查询"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.emotion_model import EmotionSnapshot


class EmotionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        emotion_type: str,
        intensity: float,
        valence: float,
        arousal: float,
        keywords: list | None = None,
        trigger: str | None = None,
        summary: str | None = None,
        evidence: str = "",
        source: str = "llm",
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> EmotionSnapshot:
        snapshot = EmotionSnapshot(
            user_id=user_id,
            emotion_type=emotion_type,
            intensity=intensity,
            valence=valence,
            arousal=arousal,
            keywords=keywords or [],
            trigger=trigger,
            summary=summary,
            evidence=evidence[:2000],
            source=source,
            conversation_id=conversation_id,
            message_id=message_id,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self.session.add(snapshot)
        await self.session.commit()
        await self.session.refresh(snapshot)
        return snapshot

    async def list_recent(
        self, user_id: UUID, *, days: int = 7, limit: int = 200
    ) -> list[EmotionSnapshot]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(EmotionSnapshot)
            .where(EmotionSnapshot.user_id == user_id, EmotionSnapshot.created_at >= since)
            .order_by(EmotionSnapshot.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_range(
        self,
        user_id: UUID,
        *,
        start: datetime,
        end: datetime | None = None,
        limit: int = 2000,
    ) -> list[EmotionSnapshot]:
        stmt = select(EmotionSnapshot).where(
            EmotionSnapshot.user_id == user_id, EmotionSnapshot.created_at >= start
        )
        if end is not None:
            stmt = stmt.where(EmotionSnapshot.created_at <= end)
        stmt = stmt.order_by(EmotionSnapshot.created_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, snapshot_id: UUID, user_id: UUID) -> EmotionSnapshot | None:
        result = await self.session.execute(
            select(EmotionSnapshot).where(
                EmotionSnapshot.id == snapshot_id, EmotionSnapshot.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, snapshot: EmotionSnapshot) -> None:
        await self.session.delete(snapshot)
        await self.session.commit()

    async def count(self, user_id: UUID, *, days: int | None = None) -> int:
        stmt = select(func.count(EmotionSnapshot.id)).where(EmotionSnapshot.user_id == user_id)
        if days:
            stmt = stmt.where(
                EmotionSnapshot.created_at >= datetime.now(timezone.utc) - timedelta(days=days)
            )
        return int((await self.session.execute(stmt)).scalar_one())
