"""兴趣数据访问层:兴趣节点(向量/时间线/统计) + 提及记录"""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.agent.interest.normalizer import compute_status, merge_aliases
from ..models.interest_model import InterestMention, InterestNode


class InterestRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 查询 ----------
    async def get_by_key(self, user_id: UUID, key: str) -> InterestNode | None:
        result = await self.session.execute(
            select(InterestNode).where(InterestNode.user_id == user_id, InterestNode.key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, interest_id: UUID, user_id: UUID) -> InterestNode | None:
        result = await self.session.execute(
            select(InterestNode).where(InterestNode.id == interest_id, InterestNode.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_nodes(
        self,
        user_id: UUID,
        *,
        category: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[InterestNode]:
        stmt = select(InterestNode).where(InterestNode.user_id == user_id)
        if category:
            stmt = stmt.where(InterestNode.category == category)
        if status:
            stmt = stmt.where(InterestNode.status == status)
        stmt = stmt.order_by(InterestNode.last_seen.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_keys(self, user_id: UUID, keys: list[str]) -> list[InterestNode]:
        if not keys:
            return []
        result = await self.session.execute(
            select(InterestNode).where(InterestNode.user_id == user_id, InterestNode.key.in_(keys))
        )
        return list(result.scalars().all())

    async def list_mentions(
        self, user_id: UUID, interest_id: UUID, limit: int = 20
    ) -> list[InterestMention]:
        result = await self.session.execute(
            select(InterestMention)
            .where(
                InterestMention.user_id == user_id,
                InterestMention.interest_id == interest_id,
            )
            .order_by(InterestMention.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_vector(
        self, user_id: UUID, query_vector: list, top_k: int = 5
    ) -> list[tuple[InterestNode, float]]:
        similarity = (1 - InterestNode.embedding.cosine_distance(query_vector)).label("similarity")
        result = await self.session.execute(
            select(InterestNode, similarity)
            .where(InterestNode.user_id == user_id, InterestNode.embedding.is_not(None))
            .order_by(InterestNode.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        return [(row[0], float(row[1])) for row in result.all()]

    async def search_by_keyword(self, user_id: UUID, keyword: str, limit: int = 5) -> list[InterestNode]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        pattern = f"%{kw}%"
        result = await self.session.execute(
            select(InterestNode)
            .where(
                InterestNode.user_id == user_id,
                or_(
                    InterestNode.name.ilike(pattern),
                    InterestNode.key.ilike(pattern),
                    cast(InterestNode.aliases, Text).ilike(pattern),
                ),
            )
            .order_by(InterestNode.mention_count.desc(), InterestNode.last_seen.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def top_active(self, user_id: UUID, limit: int = 5) -> list[InterestNode]:
        result = await self.session.execute(
            select(InterestNode)
            .where(InterestNode.user_id == user_id)
            .order_by(InterestNode.mention_count.desc(), InterestNode.last_seen.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent(
        self, user_id: UUID, since: datetime, limit: int = 10
    ) -> list[InterestNode]:
        """最近被写入/更新的关注实体(用于聊天里提示"已加入兴趣")"""
        result = await self.session.execute(
            select(InterestNode)
            .where(
                InterestNode.user_id == user_id,
                InterestNode.updated_at >= since,
            )
            .order_by(InterestNode.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_message_evidence(
        self, user_id: UUID, keyword: str, limit: int = 5
    ) -> list[tuple[str, datetime | None]]:
        """在用户真实消息里找包含该实体的句子(节点详情卡的原话证据)"""
        from ..models.conversation_model import Conversation, Message

        kw = (keyword or "").strip()
        if not kw:
            return []
        rows = await self.session.execute(
            select(Message.content, Message.created_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.user_id == user_id,
                Message.role == "user",
                Message.content.ilike(f"%{kw}%"),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in rows.all()]

    # ---------- 写入 ----------
    async def upsert_node(
        self,
        *,
        user_id: UUID,
        key: str,
        name: str,
        category: str,
        entity_type: str | None = None,
        aliases: list | None = None,
        embedding: list | None = None,
        since: date | None = None,
        until: date | None = None,
        importance: int = 0,
        last_seen: datetime | None = None,
        revive: bool = False,
    ) -> tuple[InterestNode, bool]:
        """按 (user_id, key) 幂等更新;返回 (节点, 是否新建)"""
        node = await self.get_by_key(user_id, key)
        now = datetime.now(timezone.utc)
        seen_at = last_seen or now  # 回填历史对话时用消息时间,而不是"现在"
        created = node is None
        if created:
            node = InterestNode(
                user_id=user_id,
                key=key,
                name=name,
                category=category,
                entity_type=entity_type,
                aliases=merge_aliases(None, aliases),
                embedding=embedding,
                since=since,
                until=until,
                first_seen=seen_at,
                last_seen=seen_at,
                mention_count=1,
                importance=importance,
            )
            self.session.add(node)
            await self.session.flush()
        else:
            if name:
                node.name = name
            if category:
                node.category = category
            if entity_type:
                node.entity_type = entity_type
            node.aliases = merge_aliases(node.aliases, aliases)
            if embedding is not None:
                node.embedding = embedding
            if since and (node.since is None or since < node.since):
                node.since = since
            if until:
                node.until = until
            # 只有"重新关注"且给出了新的开始时间(晚于旧结束时间)时才清掉结束时间。
            # 普通提及、或没给时间的新提及,都不复活已冷却的兴趣。
            elif revive and node.until and since and since >= node.until:
                node.until = None
            node.last_seen = seen_at
            node.mention_count = (node.mention_count or 0) + 1
            if importance:
                node.importance = importance

        node.status = compute_status(node.until, node.last_seen, node.mention_count)
        await self.session.commit()
        await self.session.refresh(node)
        return node, created

    async def add_mention(
        self,
        *,
        user_id: UUID,
        interest_id: UUID,
        raw_text: str = "",
        since: date | None = None,
        until: date | None = None,
        confidence: float = 0.0,
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> InterestMention:
        mention = InterestMention(
            user_id=user_id,
            interest_id=interest_id,
            raw_text=raw_text[:2000],
            since=since,
            until=until,
            confidence=confidence,
            conversation_id=conversation_id,
            message_id=message_id,
            created_at=created_at or datetime.now(timezone.utc),
        )
        self.session.add(mention)
        await self.session.commit()
        await self.session.refresh(mention)
        return mention

    async def mark_graph_synced(self, node: InterestNode, synced: bool) -> None:
        node.graph_synced_at = datetime.now(timezone.utc) if synced else None
        await self.session.commit()

    async def merge_into(self, user_id: UUID, keep_key: str, drop_key: str) -> bool:
        """把 drop 节点合并进 keep:迁移提及、合并时间/计数/别名,删除 drop"""
        from sqlalchemy import update as sa_update

        from ..core.agent.interest.normalizer import merge_aliases

        keep = await self.get_by_key(user_id, keep_key)
        drop = await self.get_by_key(user_id, drop_key)
        if keep is None or drop is None:
            return False
        await self.session.execute(
            sa_update(InterestMention)
            .where(InterestMention.interest_id == drop.id)
            .values(interest_id=keep.id)
        )
        keep.aliases = merge_aliases(keep.aliases, list(drop.aliases or []) + [drop.name])
        if drop.since and (keep.since is None or drop.since < keep.since):
            keep.since = drop.since
        if drop.until and (keep.until is None or drop.until > keep.until):
            keep.until = drop.until
        if drop.last_seen and (keep.last_seen is None or drop.last_seen > keep.last_seen):
            keep.last_seen = drop.last_seen
        keep.mention_count = (keep.mention_count or 0) + (drop.mention_count or 0)
        if keep.embedding is None and drop.embedding is not None:
            keep.embedding = drop.embedding
        keep.status = compute_status(keep.until, keep.last_seen, keep.mention_count)
        await self.session.delete(drop)
        await self.session.commit()
        return True

    async def delete(self, node: InterestNode) -> None:
        await self.session.delete(node)
        await self.session.commit()

    # ---------- 统计 ----------
    async def summary(self, user_id: UUID) -> dict:
        now = datetime.now(timezone.utc)
        total = (
            await self.session.execute(
                select(func.count(InterestNode.id)).where(InterestNode.user_id == user_id)
            )
        ).scalar_one()
        active = (
            await self.session.execute(
                select(func.count(InterestNode.id)).where(
                    InterestNode.user_id == user_id, InterestNode.status == "active"
                )
            )
        ).scalar_one()
        new_30d = (
            await self.session.execute(
                select(func.count(InterestNode.id)).where(
                    InterestNode.user_id == user_id,
                    InterestNode.first_seen >= now - timedelta(days=30),
                )
            )
        ).scalar_one()
        cat_rows = (
            await self.session.execute(
                select(InterestNode.category, func.count(InterestNode.id))
                .where(InterestNode.user_id == user_id)
                .group_by(InterestNode.category)
            )
        ).all()
        longest = (
            await self.session.execute(
                select(InterestNode)
                .where(InterestNode.user_id == user_id)
                .order_by(InterestNode.first_seen.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return {
            "total_count": int(total),
            "active_count": int(active),
            "cooled_count": int(total) - int(active),
            "new_last_30d": int(new_30d),
            "category_dist": {str(c): int(n) for c, n in cat_rows},
            "longest_interest": (
                {
                    "id": str(longest.id),
                    "name": longest.name,
                    "category": longest.category,
                    "first_seen": longest.first_seen.isoformat() if longest.first_seen else None,
                }
                if longest
                else None
            ),
        }
