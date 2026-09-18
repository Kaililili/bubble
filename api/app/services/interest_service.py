"""兴趣业务逻辑:时间线 / 图谱 / 统计 / 详情 / 删除 / 多跳检索"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.agent.interest.graph_repo import InterestGraphRepo
from ..core.exceptions import AppException
from ..repositories.interest_repository import InterestRepository


class InterestService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = InterestRepository(session)
        self.graph_repo = InterestGraphRepo()

    async def timeline(
        self, user_id: UUID, category: str | None = None, status: str | None = None
    ) -> list:
        return await self.repo.list_nodes(user_id, category=category, status=status)

    async def summary(self, user_id: UUID) -> dict:
        return await self.repo.summary(user_id)

    async def recent(self, user_id: UUID, since, limit: int = 10) -> list[dict]:
        """最近新增/更新的关注实体(聊天里提示"已加入兴趣")"""
        from datetime import datetime, timedelta, timezone

        if since is None:
            since = datetime.now(timezone.utc) - timedelta(minutes=5)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        nodes = await self.repo.list_recent(user_id, since, limit)
        return [
            {
                "id": str(n.id),
                "name": n.name,
                "category": n.category,
                "entity_type": n.entity_type,
                "status": n.status,
                "mention_count": n.mention_count,
                "is_new": bool(n.created_at and n.created_at >= since),
                "updated_at": n.updated_at.isoformat() if n.updated_at else None,
            }
            for n in nodes
        ]

    async def entity_detail(self, user_id: UUID, key: str) -> dict:
        """节点详情:是否关注 + 类型/时间 + 连接到的关注实体与关系 + 出现的原句"""
        node = await self.repo.get_by_key(user_id, key)
        try:
            links = await self.graph_repo.entity_links(user_id=user_id, key=key)
        except Exception:  # noqa: BLE001
            links = []
        entities = await self.graph_repo.list_entities(user_id=user_id, limit=200)
        meta = next((e for e in entities if e.get("key") == key), None)
        keyword = (node.name if node else None) or (meta or {}).get("name") or key
        rows = await self.repo.search_message_evidence(user_id, keyword, limit=12)
        # 只保留陈述句:问句(「X 是什么关系/有没有关注过」)不是兴趣证据
        import re

        question_re = re.compile(r"[?？]|吗\s*$|什么|哪些|是不是|有没有|怎么")
        rows = [row for row in rows if not question_re.search(row[0] or "")][:5]

        def link_display(item: dict) -> str:
            name = meta.get("name") if meta else key
            rel = item.get("relation") or "related"
            other = item.get("entity_name") or item.get("entity_key")
            if item.get("direction") == "from_entity":
                return f"{name} -{rel}-> {other}"
            return f"{other} -{rel}-> {name}"

        statement_evidence = await self._statement_evidence(user_id, key)
        return {
            "key": key,
            "name": (node.name if node else None) or (meta or {}).get("name") or key,
            "type": (node.entity_type if node else None) or (meta or {}).get("type"),
            "category": (node.category if node else None) or (meta or {}).get("category"),
            "followed": node is not None,
            "status": node.status if node else None,
            "since": str(node.since) if node and node.since else None,
            "until": str(node.until) if node and node.until else None,
            "mention_count": node.mention_count if node else None,
            "links": [{**item, "display": link_display(item)} for item in links],
            "evidence": statement_evidence or [
                {
                    "text": content,
                    "at": created_at.isoformat() if created_at else None,
                    "from_entity": "",
                }
                for content, created_at in rows
            ],
        }

    async def _statement_evidence(self, user_id: UUID, key: str) -> list[dict]:
        """节点详情的原句证据:优先读图里的 Statement(与图谱同源),失败返回空由上层兜底"""
        try:
            rows = await self.graph_repo.statements_for_entity(user_id=user_id, key=key, limit=5)
        except Exception:  # noqa: BLE001
            return []
        out: list[dict] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            if text:
                out.append(
                    {"text": text, "at": str(row.get("occurred_at") or "") or None, "from_entity": ""}
                )
        return out

    async def graph(self, user_id: UUID, limit: int = 100) -> dict:
        """图数据:关注实体(INTERESTED_IN)+ 关联实体 + 实体间关系边。

        图里没有"兴趣"节点类型:关注实体按 kind=followed 标记,其余实体 kind=related。
        图库不可用时降级为纯关注实体节点(PG 出,无关联)。
        """
        nodes = [
            {
                "id": f"entity:{n.key}",
                "label": n.name,
                "type": n.entity_type or "other",
                "kind": "followed",
                "category": n.category,
                "status": n.status,
                "mention_count": n.mention_count,
                "description": None,
            }
            for n in await self.repo.list_nodes(user_id, limit=limit)
        ]
        edges: list[dict] = []
        reason: str | None = None
        try:
            data = await self.graph_repo.fetch_graph(user_id=user_id, limit=limit)
            followed_keys = {n["key"] for n in data["followed"]}
            for ent in data["related"]:
                if ent["key"] in followed_keys:
                    continue
                nodes.append(
                    {
                        "id": f"entity:{ent['key']}",
                        "label": ent["name"],
                        "type": ent.get("type") or "other",
                        "kind": "related",
                        "category": ent.get("category"),
                        "status": None,
                        "mention_count": None,
                        "description": None,
                    }
                )
            for edge in data["edges"]:
                edges.append(
                    {
                        "source": f"entity:{edge['source']}",
                        "target": f"entity:{edge['target']}",
                        "type": edge.get("type") or "related",
                        "weight": edge.get("weight") or 1,
                    }
                )
        except Exception as e:  # noqa: BLE001
            reason = str(e)[:200]
        # 去重:同一实体/边可能被多条路径重复返回
        unique_nodes = {n["id"]: n for n in nodes}
        unique_edges = {
            (e["source"], e["target"], e["type"]): e for e in edges if e["source"] != e["target"]
        }
        return {
            "available": reason is None,
            "reason": reason,
            "nodes": list(unique_nodes.values()),
            "edges": list(unique_edges.values()),
        }

    async def detail(self, user_id: UUID, interest_id: UUID) -> dict:
        node = await self.repo.get_by_id(interest_id, user_id)
        if not node:
            raise AppException(code=404, message="兴趣不存在")
        mentions = await self.repo.list_mentions(user_id, interest_id, limit=20)
        return {"interest": node, "mentions": mentions}

    async def delete(self, user_id: UUID, interest_id: UUID) -> dict:
        node = await self.repo.get_by_id(interest_id, user_id)
        if not node:
            raise AppException(code=404, message="兴趣不存在")
        graph_deleted = True
        try:
            await self.graph_repo.delete_interest(user_id=user_id, key=node.key)
        except Exception:  # noqa: BLE001
            graph_deleted = False  # 图库不可用时先删 PG,图数据留待重建清理
        key = node.key
        await self.repo.delete(node)
        return {"key": key, "graph_deleted": graph_deleted}

    async def recall(
        self,
        user_id: UUID,
        query: str = "",
        *,
        hops: int = 2,
        include_cooled: bool = True,
        limit: int = 8,
    ) -> dict:
        from ..core.agent.interest.retriever import recall as graph_recall

        return await graph_recall(
            self.session,
            user_id,
            query,
            hops=hops,
            include_cooled=include_cooled,
            limit=limit,
        )
