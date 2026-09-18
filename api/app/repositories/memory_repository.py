"""记忆数据访问层:用户背景 + 长尾记忆"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory_model import Memory, UserProfile


class UserProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: UUID) -> list[UserProfile]:
        result = await self.session.execute(
            select(UserProfile)
            .where(UserProfile.user_id == user_id)
            .order_by(UserProfile.importance.desc(), UserProfile.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, profile_id: UUID, user_id: UUID) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.id == profile_id, UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_key(self, user_id: UUID, key: str) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id, UserProfile.key == key)
        )
        return result.scalar_one_or_none()

    async def upsert(self, user_id: UUID, key: str, value: str, importance: int = 0) -> UserProfile:
        profile = await self.get_by_key(user_id, key)
        if profile:
            profile.value = value
            profile.importance = importance
        else:
            profile = UserProfile(user_id=user_id, key=key, value=value, importance=importance)
            self.session.add(profile)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def delete(self, profile: UserProfile) -> None:
        await self.session.delete(profile)
        await self.session.commit()


class MemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        type: str,
        content: str,
        content_encrypted: str | None = None,
        embedding: list | None = None,
        importance: int = 0,
    ) -> Memory:
        memory = Memory(
            user_id=user_id,
            type=type,
            content=content,
            content_encrypted=content_encrypted,
            embedding=embedding,
            importance=importance,
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def list_by_user(
        self, user_id: UUID, type: str | None = None, keyword: str | None = None
    ) -> list[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id)
        if type:
            stmt = stmt.where(Memory.type == type)
        if keyword:
            stmt = stmt.where(Memory.content.ilike(f"%{keyword}%"))
        stmt = stmt.order_by(Memory.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, memory_id: UUID, user_id: UUID) -> Memory | None:
        result = await self.session.execute(
            select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, memory: Memory) -> None:
        await self.session.delete(memory)
        await self.session.commit()

    async def update(self, memory: Memory) -> Memory:
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def find_credential_by_key(self, user_id: UUID, key: str) -> Memory | None:
        """按归一化应用 key 查找同一条凭证,用于覆盖更新。"""
        from ..core.security import credential_key

        result = await self.session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.type == "credential")
        )
        for m in result.scalars().all():
            if credential_key(m.content or "") == key:
                return m
        return None

    async def delete_by_keyword(self, user_id: UUID, keyword: str) -> bool:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.content.ilike(f"%{keyword}%"))
            .limit(1)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            return False
        await self.session.delete(memory)
        await self.session.commit()
        return True

    async def search_by_vector(self, user_id: UUID, query_vector: list, top_k: int = 5) -> list[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.embedding.is_not(None))
            .order_by(Memory.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        return list(result.scalars().all())

    async def search_by_keyword(self, user_id: UUID, keyword: str, limit: int = 5) -> list[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.content.ilike(f"%{keyword}%"))
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_candidates(
        self,
        user_id: UUID,
        query_vector: list | None = None,
        keyword: str | None = None,
        limit: int = 20,
        include_superseded: bool = False,
    ) -> list[tuple[Memory, float | None]]:
        """召回候选池:向量相似度 + 关键词,供融合排序使用。

        返回 [(记忆, 向量相似度 or None)];纯关键词命中的条目相似度为 None。
        """
        pool: dict = {}
        if query_vector is not None:
            result = await self.session.execute(
                select(
                    Memory,
                    (1 - Memory.embedding.cosine_distance(query_vector)).label("similarity"),
                )
                .where(
                    Memory.user_id == user_id,
                    Memory.embedding.is_not(None),
                    *(() if include_superseded else (Memory.status == "active",)),
                )
                .order_by(Memory.embedding.cosine_distance(query_vector))
                .limit(limit)
            )
            for memory, similarity in result.all():
                pool[memory.id] = (memory, float(similarity))
        if keyword:
            result = await self.session.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.content.ilike(f"%{keyword}%"),
                    *(() if include_superseded else (Memory.status == "active",)),
                )
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            for memory in result.scalars().all():
                pool.setdefault(memory.id, (memory, None))
        return list(pool.values())

    async def touch_accessed(self, memories: list[Memory]) -> None:
        """命中回写:访问次数 +1、记录最近访问时间(供融合排序与后续分层巩固)"""
        if not memories:
            return
        now = datetime.now(timezone.utc)
        for memory in memories:
            memory.access_count = (memory.access_count or 0) + 1
            memory.last_accessed_at = now
        await self.session.commit()

    async def supersede(self, old: Memory, new_memory_id) -> None:
        """把旧记忆标记为被取代(不物理删除,面板可查历史版本)"""
        old.status = "superseded"
        old.superseded_by = new_memory_id
        await self.session.commit()

    async def list_top_for_insight(self, user_id: UUID, limit: int = 20) -> list[Memory]:
        """洞察层输入:按重要度与使用次数取高价值记忆;排除凭证与已失效记忆"""
        result = await self.session.execute(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.type != "credential",
                Memory.status == "active",
            )
            .order_by(
                Memory.importance.desc(),
                Memory.access_count.desc(),
                Memory.created_at.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())
