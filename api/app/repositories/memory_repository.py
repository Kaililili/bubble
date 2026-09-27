"""记忆数据访问层:用户背景 + 长尾记忆"""
import math
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory_model import Memory, UserProfile

_KEY_NOISE_RE = re.compile(r"[\s:：_\-·/]+")


def normalize_profile_key(key: str) -> str:
    """背景字段名归一化(大小写/空格/分隔符不敏感),用于"同一个字段"判定"""
    return _KEY_NOISE_RE.sub("", key or "").strip().lower()


def similar_profile_key(a: str, b: str) -> bool:
    """两个背景字段名是否指向同一属性(包含关系,或共享同一个 2 字属性词尾)"""
    na, nb = normalize_profile_key(a), normalize_profile_key(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return len(na) >= 2 and len(nb) >= 2 and na[-2:] == nb[-2:]


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
        # 字段名先按归一化匹配:大小写/空格差异不产生第二行(避免"同一属性两处不一致")
        profile = await self.get_by_key(user_id, key)
        if profile is None:
            for row in await self.list_by_user(user_id):
                if normalize_profile_key(row.key) == normalize_profile_key(key):
                    profile = row
                    break
        if profile:
            profile.key = key
            profile.value = value
            profile.importance = importance
        else:
            profile = UserProfile(user_id=user_id, key=key, value=value, importance=importance)
            self.session.add(profile)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def find_similar_key_conflicts(
        self, user_id: UUID, key: str, value: str
    ) -> list[UserProfile]:
        """同一属性名下的旧值:字段名相近但当前值不同(提示调用方统一字段名/更新值)"""
        out: list[UserProfile] = []
        for row in await self.list_by_user(user_id):
            if row.key == key:
                continue
            if similar_profile_key(row.key, key) and (row.value or "").strip() != (value or "").strip():
                out.append(row)
        return out

    async def superseded_since(self, user_id: UUID, since: datetime | None) -> list[Memory]:
        """某时间点之后被新事实取代的旧记忆(用于抑制已过时的背景值注入)"""
        stmt = select(Memory).where(Memory.user_id == user_id, Memory.status == "superseded")
        if since is not None:
            stmt = stmt.where(Memory.updated_at >= since)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
        source: str | None = None,
        source_message_id: UUID | None = None,
        attribute: str | None = None,
        scope: str | None = None,
    ) -> Memory:
        memory = Memory(
            user_id=user_id,
            type=type,
            content=content,
            content_encrypted=content_encrypted,
            embedding=embedding,
            importance=importance,
            source=source,
            source_message_id=source_message_id,
            attribute=attribute,
            scope=scope,
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def insert_fact(
        self,
        *,
        user_id: UUID,
        content: str,
        embedding: list | None = None,
        source: str | None = None,
        source_message_id: UUID | None = None,
        attribute: str | None = None,
        scope: str | None = None,
    ) -> Memory:
        """创建普通事实但**只 flush 不 commit**,供 upsert_fact 在同一事务里标记 superseded"""
        memory = Memory(
            user_id=user_id,
            type="fact",
            content=content,
            embedding=embedding,
            source=source,
            source_message_id=source_message_id,
            attribute=attribute,
            scope=scope,
        )
        self.session.add(memory)
        await self.session.flush()
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

    async def find_active_by_content(self, user_id: UUID, type: str, content: str) -> Memory | None:
        """幂等检查:同类型 + 归一化文本完全相同 + 仍有效的记忆"""
        from ..core.agent.memory.supersede import normalize_fact

        target = normalize_fact(content)
        if not target:
            return None
        result = await self.session.execute(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.type == type,
                Memory.status == "active",
            )
        )
        for memory in result.scalars().all():
            if normalize_fact(memory.content or "") == target:
                return memory
        return None

    async def search_active(
        self,
        user_id: UUID,
        *,
        query_vector: list | None = None,
        keyword: str | None = None,
        limit: int = 5,
    ) -> list[Memory]:
        """只召回仍有效(active)的记忆,供删除类操作使用:失效历史不参与候选。

        排序:内容精确命中的排在最前,否则按向量相似度。
        """
        candidates = await self.search_candidates(
            user_id, query_vector, keyword, limit=limit, include_superseded=False
        )
        key = (keyword or "").strip()
        candidates.sort(
            key=lambda item: (
                0 if key and key in (item[0].content or "") else 1,
                -(item[1] or 0.0),
            )
        )
        return [memory for memory, _sim in candidates]

    async def count_matching(self, user_id: UUID, keyword: str, status: str | None = None) -> int:
        """按关键词统计记忆条数(可按状态过滤),用于向用户说明命中的是失效历史版本"""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Memory).where(
            Memory.user_id == user_id, Memory.content.ilike(f"%{keyword}%")
        )
        if status:
            stmt = stmt.where(Memory.status == status)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

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
        type: str | None = None,
    ) -> list[tuple[Memory, float | None]]:
        """召回候选池:向量相似度 + 关键词,供融合排序使用。

        返回 [(记忆, 向量相似度 or None)];纯关键词命中的条目相似度为 None。
        """
        pool: dict = {}
        type_cond = (Memory.type == type,) if type else ()
        if query_vector is not None:
            result = await self.session.execute(
                select(
                    Memory,
                    (1 - Memory.embedding.cosine_distance(query_vector)).label("similarity"),
                )
                .where(
                    Memory.user_id == user_id,
                    Memory.embedding.is_not(None),
                    *type_cond,
                    *(() if include_superseded else (Memory.status == "active",)),
                )
                .order_by(Memory.embedding.cosine_distance(query_vector))
                .limit(limit)
            )
            for memory, similarity in result.all():
                sim = float(similarity) if similarity is not None else 0.0
                if math.isnan(sim):
                    sim = 0.0  # 零向量/退化向量会得到 NaN 距离,按无相似度处理
                pool[memory.id] = (memory, sim)
        if keyword:
            result = await self.session.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.content.ilike(f"%{keyword}%"),
                    *type_cond,
                    *(() if include_superseded else (Memory.status == "active",)),
                )
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            for memory in result.scalars().all():
                pool.setdefault(memory.id, (memory, None))
        return list(pool.values())

    async def find_update_candidates(
        self,
        user_id: UUID,
        type: str,
        attribute: str | None,
        scope: str | None,
        embedding: list | None,
        content: str,
        limit: int = 6,
    ) -> list[Memory]:
        """合并属性/适用范围/向量/文本候选,按相关度做**确定性排序**后再截断。

        只在同用户、同类型、active 里找。属性/适用范围命中是加分项,不是覆盖依据;
        排序键 = 向量相似度 + 属性命中加分 + 适用范围命中加分 + 文本命中加分,
        最后用创建时间与 id 做确定性 tie-break。这样即使同属性记录超过 limit,
        向量最相近或文本命中的目标旧事实也不会被顺序截掉。
        """
        from ..core.agent.memory.supersede import normalize_fact

        norm_content = normalize_fact(content)
        entries: dict = {}  # memory.id -> {memory, attr, scope, sim, text}

        def add(memory, *, attr=False, scope=False, sim=None, text=0) -> None:
            entry = entries.get(memory.id)
            if entry is None:
                entries[memory.id] = {
                    "memory": memory,
                    "attr": attr,
                    "scope": scope,
                    "sim": sim,
                    "text": text,
                }
                return
            entry["attr"] = entry["attr"] or attr
            entry["scope"] = entry["scope"] or scope
            if sim is not None and (entry["sim"] is None or sim > entry["sim"]):
                entry["sim"] = sim
            entry["text"] = max(entry["text"], text)

        if attribute:
            result = await self.session.execute(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.type == type,
                    Memory.status == "active",
                    Memory.attribute == attribute,
                )
                .limit(100)
            )
            for memory in result.scalars().all():
                add(memory, attr=True, scope=bool(scope) and memory.scope == scope)

        if scope:
            result = await self.session.execute(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.type == type,
                    Memory.status == "active",
                    Memory.scope == scope,
                )
                .limit(100)
            )
            for memory in result.scalars().all():
                add(memory, scope=True, attr=bool(attribute) and memory.attribute == attribute)

        # 向量 + 文本(把关键词检索上限放大,避免排序前就丢掉向量命中的关键旧事实)
        candidates = await self.search_candidates(
            user_id,
            embedding,
            content,
            limit=limit * 4,
            include_superseded=False,
            type=type,
        )
        for memory, similarity in candidates:
            norm_old = normalize_fact(memory.content or "")
            text = 2 if norm_old == norm_content else (
                1 if norm_content and (norm_content in norm_old or norm_old in norm_content) else 0
            )
            add(memory, sim=similarity, text=text)

        def sort_key(entry):
            sim = entry["sim"]
            if sim is None or math.isnan(sim):
                sim = 0.0
            score = (
                sim
                + 0.5 * (1 if entry["attr"] else 0)
                + 0.25 * (1 if entry["scope"] else 0)
                + 0.5 * entry["text"]
            )
            created = entry["memory"].created_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
            return (score, created, str(entry["memory"].id))

        ranked = sorted(entries.values(), key=sort_key, reverse=True)
        return [entry["memory"] for entry in ranked][:limit]

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
