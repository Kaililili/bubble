"""情绪业务逻辑:曲线 / 分布 / 词云 / 触发事件 / 画像"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.agent.emotion.aggregator import (
    aggregate_profile,
    bucket_history,
    build_wordcloud,
    emotion_distribution,
)
from ..core.exceptions import AppException
from ..repositories.emotion_repository import EmotionRepository


class EmotionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = EmotionRepository(session)

    async def history(self, user_id: UUID, granularity: str = "day", days: int = 30) -> list[dict]:
        start = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
        rows = await self.repo.list_range(user_id, start=start)
        return bucket_history(rows, granularity)

    async def summary(self, user_id: UUID, days: int = 30) -> dict:
        days = max(1, min(days, 365))
        rows = await self.repo.list_recent(user_id, days=days, limit=1000)
        profile = aggregate_profile(rows)
        triggers = Counter(r.trigger for r in rows if r.trigger)
        return {
            "days": days,
            "count": profile.sample_count,
            "avg_valence": profile.avg_valence,
            "avg_arousal": profile.avg_arousal,
            "dominant_emotion": profile.dominant_emotion,
            "trend": profile.trend,
            "negative_ratio": profile.negative_ratio,
            "distribution": emotion_distribution(rows),
            "top_triggers": [
                {"trigger": t, "count": c} for t, c in triggers.most_common(5)
            ],
        }

    async def profile(self, user_id: UUID, days: int = 7) -> dict:
        rows = await self.repo.list_recent(user_id, days=max(1, min(days, 90)), limit=20)
        agg = aggregate_profile(rows)
        return {
            "dominant_emotion": agg.dominant_emotion,
            "avg_valence": agg.avg_valence,
            "avg_arousal": agg.avg_arousal,
            "sample_count": agg.sample_count,
            "trend": agg.trend,
            "recent_triggers": agg.recent_triggers,
            "negative_ratio": agg.negative_ratio,
        }

    async def wordcloud(self, user_id: UUID, days: int = 30) -> list[dict]:
        rows = await self.repo.list_recent(user_id, days=max(1, min(days, 365)), limit=1000)
        return build_wordcloud(rows)

    async def events(self, user_id: UUID, limit: int = 20) -> list:
        return await self.repo.list_recent(user_id, days=3650, limit=max(1, min(limit, 100)))

    async def delete(self, user_id: UUID, snapshot_id: UUID) -> None:
        snapshot = await self.repo.get_by_id(snapshot_id, user_id)
        if not snapshot:
            raise AppException(code=404, message="情绪记录不存在")
        await self.repo.delete(snapshot)
