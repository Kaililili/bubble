"""Neo4j 图仓储:只有 Entity 与实体间关联。

数据模型(2026-09-13 统一):
  (:User {id})
  (:Entity {user_id, key, name, type, category, description, aliases})
  (User)-[:INTERESTED_IN {since, until, status, last_seen, mention_count}]->(Entity)   ← "兴趣"就是这条边
  (Entity)-[:RELATED {type, weight, description}]->(Entity)                            ← type: broader/related/member_of/part_of/co_occur

约定:所有查询以 (:User {id}) 为锚点,节点带 user_id 双保险,不跨用户遍历。
"""
import logging
import uuid
from datetime import datetime, timezone

from ....db.neo4j import neo4j_client

logger = logging.getLogger(__name__)

MAX_HOPS = 3
_CONSTRAINTS = (
    "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT entity_key_unique IF NOT EXISTS FOR (n:Entity) REQUIRE (n.user_id, n.key) IS UNIQUE",
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
    # Statement 溯源层:同一用户下 sid 唯一(幂等写)
    "CREATE CONSTRAINT statement_sid_unique IF NOT EXISTS FOR (n:Statement) REQUIRE (n.user_id, n.sid) IS UNIQUE",
    "CREATE INDEX statement_occurred IF NOT EXISTS FOR (n:Statement) ON (n.occurred_at)",
)


class InterestGraphRepo:
    """实体图谱读写;Neo4j 不可用时抛异常,由上层降级"""

    async def available(self) -> bool:
        try:
            await neo4j_client.verify_connectivity()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Neo4j unavailable: %s", e)
            return False

    async def ensure_constraints(self) -> None:
        async with neo4j_client.driver.session() as session:
            for statement in _CONSTRAINTS:
                await session.run(statement)

    # ---------- 写入 ----------
    async def upsert_graph(
        self,
        *,
        user_id: uuid.UUID,
        entities: list[dict],
        relations: list[dict],
    ) -> None:
        """批量幂等写入实体与关系(单事务)。

        entities: [{key,name,type,category,description,aliases,is_followed,since,until,status}]
        relations: [{from_key,to_key,type,description,weight}]
        """
        if not entities and not relations:
            return
        entity_query = """
        MERGE (u:User {id:$uid})
        WITH u
        UNWIND (CASE WHEN size($entities) = 0 THEN [null] ELSE $entities END) AS e
        FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
            MERGE (en:Entity {user_id:$uid, key:e.key})
              SET en.name = e.name,
                  en.type = coalesce(e.type, en.type),
                  en.category = coalesce(e.category, en.category),
                  en.description = coalesce(e.description, en.description),
                  en.aliases = coalesce(e.aliases, en.aliases)
            FOREACH (_ IN CASE WHEN e.is_followed THEN [1] ELSE [] END |
                MERGE (u)-[r:INTERESTED_IN]->(en)
                  SET r.since = CASE
                        WHEN e.since IS NULL THEN r.since
                        WHEN r.since IS NULL THEN e.since
                        WHEN e.since < r.since THEN e.since
                        ELSE r.since END,
                      r.until = CASE
                        WHEN e.until IS NOT NULL THEN e.until
                        WHEN e.clear_until THEN NULL
                        ELSE r.until END,
                      r.status = coalesce(e.status, r.status),
                      r.last_seen = $now,
                      r.mention_count = coalesce(r.mention_count, 0)
                          + (CASE WHEN e.count_mention THEN 1 ELSE 0 END)
            )
        )
        """
        relation_query = """
        UNWIND $relations AS rel
        MATCH (a:Entity {user_id:$uid, key:rel.from_key})
        MATCH (b:Entity {user_id:$uid, key:rel.to_key})
        MERGE (a)-[r:RELATED {type:rel.type}]->(b)
          SET r.weight = coalesce(r.weight, 0) + 1,
              r.description = coalesce(rel.description, r.description)
        """
        now = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "key": e.get("key"),
                "name": e.get("name") or e.get("key"),
                "type": e.get("type"),
                "category": e.get("category"),
                "description": e.get("description"),
                "aliases": e.get("aliases") or [],
                "is_followed": bool(e.get("is_followed")),
                "since": e.get("since"),
                "until": e.get("until"),
                "clear_until": bool(e.get("clear_until")),
                "status": e.get("status"),
                "count_mention": bool(e.get("count_mention", True)),
            }
            for e in entities
            if e.get("key")
        ]
        async with neo4j_client.driver.session() as session:
            if payload:
                await session.run(entity_query, uid=str(user_id), entities=payload, now=now)
            rel_payload = [
                {
                        "from_key": rel["from_key"],
                        "to_key": rel["to_key"],
                        "type": rel.get("type") or "related",
                        "description": rel.get("description"),
                }
                for rel in (relations or [])
                if rel.get("from_key") and rel.get("to_key")
            ]
            if rel_payload:
                await session.run(relation_query, uid=str(user_id), relations=rel_payload)

    async def delete_interest(self, *, user_id: uuid.UUID, key: str) -> None:
        """删除"关注"关系;顺手清掉不再被引用的孤立实体"""
        delete_edge = """
        MATCH (u:User {id:$uid})-[r:INTERESTED_IN]->(e:Entity {key:$key})
        DELETE r
        """
        cleanup = """
        MATCH (e:Entity {user_id:$uid})
        WHERE NOT (e)--()
        DETACH DELETE e
        """
        async with neo4j_client.driver.session() as session:
            await session.run(delete_edge, uid=str(user_id), key=key)
            await session.run(cleanup, uid=str(user_id))

    async def list_entities(self, *, user_id: uuid.UUID, limit: int = 500) -> list[dict]:
        """列出该用户的全部实体(含未被关注的),用于实体消解"""
        query = """
        MATCH (e:Entity {user_id:$uid})
        OPTIONAL MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(e)
        RETURN e.key AS key, e.name AS name, e.type AS type, e.category AS category,
               e.aliases AS aliases, (u IS NOT NULL) AS followed
        ORDER BY followed DESC, e.name LIMIT $limit
        """
        async with neo4j_client.driver.session() as session:
            return await (await session.run(query, uid=str(user_id), limit=limit)).data()

    async def entity_links(self, *, user_id: uuid.UUID, key: str) -> list[dict]:
        """某个实体的所有邻居实体及关系(用于节点详情卡;含是否为关注实体)"""
        query = """
        MATCH (e:Entity {user_id:$uid, key:$key})
        MATCH (e)-[r:RELATED]-(n:Entity {user_id:$uid})
        OPTIONAL MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(n)
        RETURN DISTINCT n.key AS entity_key, n.name AS entity_name,
               coalesce(r.type, 'related') AS relation,
               CASE WHEN startNode(r) = e THEN 'from_entity' ELSE 'to_entity' END AS direction,
               (u IS NOT NULL) AS followed
        LIMIT 20
        """
        async with neo4j_client.driver.session() as session:
            return await (await session.run(query, uid=str(user_id), key=key)).data()

    async def merge_entities(self, *, user_id: uuid.UUID, keep_key: str, drop_key: str) -> bool:
        """把 drop 实体合并进 keep:搬关注边/实体间关系,再删掉 drop 节点(幂等)"""
        if not keep_key or not drop_key or keep_key == drop_key:
            return False
        query = """
        MATCH (keep:Entity {user_id:$uid, key:$keep}), (drop:Entity {user_id:$uid, key:$drop})
        WHERE keep <> drop
        OPTIONAL MATCH (u:User {id:$uid})-[ur:INTERESTED_IN]->(drop)
        FOREACH (_ IN CASE WHEN ur IS NULL THEN [] ELSE [1] END |
            MERGE (u)-[kr:INTERESTED_IN]->(keep)
              SET kr.since = CASE
                    WHEN kr.since IS NULL THEN ur.since
                    WHEN ur.since IS NULL THEN kr.since
                    WHEN ur.since < kr.since THEN ur.since
                    ELSE kr.since END,
                  kr.until = CASE WHEN ur.until IS NOT NULL THEN ur.until ELSE kr.until END,
                  kr.last_seen = CASE
                    WHEN kr.last_seen IS NULL THEN ur.last_seen
                    WHEN ur.last_seen IS NULL THEN kr.last_seen
                    WHEN ur.last_seen > kr.last_seen THEN ur.last_seen
                    ELSE kr.last_seen END,
                  kr.mention_count = coalesce(kr.mention_count, 0) + coalesce(ur.mention_count, 0)
        )
        WITH DISTINCT keep, drop
        OPTIONAL MATCH (drop)-[r:RELATED]->(b:Entity)
        WHERE b <> keep AND b <> drop
        FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
            MERGE (keep)-[r2:RELATED {type:r.type}]->(b)
              ON CREATE SET r2.weight = coalesce(r.weight, 1)
        )
        WITH DISTINCT keep, drop
        OPTIONAL MATCH (a:Entity)-[r:RELATED]->(drop)
        WHERE a <> keep AND a <> drop
        FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
            MERGE (a)-[r2:RELATED {type:r.type}]->(keep)
              ON CREATE SET r2.weight = coalesce(r.weight, 1)
        )
        WITH DISTINCT keep, drop
        DETACH DELETE drop
        """
        try:
            async with neo4j_client.driver.session() as session:
                await session.run(query, uid=str(user_id), keep=keep_key, drop=drop_key)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("merge entities failed (%s -> %s): %s", drop_key, keep_key, e)
            return False

    # ---------- 读取 ----------
    async def fetch_graph(self, *, user_id: uuid.UUID, limit: int = 100) -> dict:
        """面板用:关注实体(followed)+ 关联实体(related) + 实体间关系边"""
        uid = str(user_id)
        async with neo4j_client.driver.session() as session:
            followed = await (
                await session.run(
                    """
                    MATCH (u:User {id:$uid})-[r:INTERESTED_IN]->(e:Entity)
                    RETURN e.key AS key, e.name AS name, e.type AS type, e.category AS category,
                           e.description AS description,
                           r.since AS since, r.until AS until, r.status AS status,
                           coalesce(r.mention_count, 0) AS mentions
                    ORDER BY mentions DESC LIMIT $limit
                    """,
                    uid=uid,
                    limit=limit,
                )
            ).data()
            related = await (
                await session.run(
                    """
                    MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(:Entity)-[:RELATED]-(e:Entity {user_id:$uid})
                    WHERE NOT (u)-[:INTERESTED_IN]->(e)
                    RETURN DISTINCT e.key AS key, e.name AS name, e.type AS type, e.category AS category
                    LIMIT $limit
                    """,
                    uid=uid,
                    limit=limit * 2,
                )
            ).data()
            edges = await (
                await session.run(
                    """
                    MATCH (u:User {id:$uid})
                    MATCH (a:Entity {user_id:$uid})-[r:RELATED]->(b:Entity {user_id:$uid})
                    WHERE (u)-[:INTERESTED_IN]->(a) OR (u)-[:INTERESTED_IN]->(b)
                    RETURN DISTINCT a.key AS source, b.key AS target,
                           coalesce(r.type, 'related') AS type, coalesce(r.weight, 1) AS weight
                    LIMIT $limit
                    """,
                    uid=uid,
                    limit=limit * 2,
                )
            ).data()
        return {"followed": followed, "related": related, "edges": edges}

    async def neighborhood(
        self, *, user_id: uuid.UUID, keys: list[str], hops: int = 2, limit: int = 8
    ) -> dict:
        """种子实体的多跳扩展:一跳/二跳邻居 + 通过共享邻居形成的桥接关注实体"""
        if not keys:
            return {"seeds": [], "neighbors": [], "bridges": []}
        uid = str(user_id)
        hops = max(1, min(int(hops or 1), MAX_HOPS))
        async with neo4j_client.driver.session() as session:
            seeds = await (
                await session.run(
                    """
                    MATCH (u:User {id:$uid})-[r:INTERESTED_IN]->(e:Entity)
                    WHERE e.key IN $keys
                    RETURN e.key AS key, e.name AS name, e.category AS category, e.type AS type,
                           r.since AS since, r.until AS until, r.status AS status,
                           coalesce(r.mention_count, 0) AS mentions
                    ORDER BY mentions DESC LIMIT $limit
                    """,
                    uid=uid,
                    keys=keys,
                    limit=limit,
                )
            ).data()
            neighbors = (
                await (
                    await session.run(
                        f"""
                        MATCH (u:User {{id:$uid}})-[:INTERESTED_IN]->(s:Entity)
                        WHERE s.key IN $keys
                        MATCH p = (s)-[:RELATED*1..{hops}]-(n:Entity {{user_id:$uid}})
                        WHERE NOT n.key IN $keys
                        RETURN DISTINCT n.key AS key, n.name AS name, n.category AS category,
                               n.type AS type, length(p) AS hops,
                               [x IN nodes(p) | x.name] AS path,
                               [r IN relationships(p) | r.type] AS rel_types,
                               s.name AS seed_name
                        ORDER BY hops ASC LIMIT $limit
                        """,
                        uid=uid,
                        keys=keys,
                        limit=limit * 2,
                    )
                ).data()
                if hops >= 1
                else []
            )
            bridges = (
                await (
                    await session.run(
                        """
                        MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(s:Entity)
                        WHERE s.key IN $keys
                        MATCH (s)-[:RELATED]-(shared:Entity {user_id:$uid})-[:RELATED]-(other:Entity)<-[:INTERESTED_IN]-(u)
                        WHERE other.key <> s.key AND NOT other.key IN $keys
                        RETURN other.key AS key, other.name AS name, other.category AS category,
                               other.type AS type,
                               collect(DISTINCT shared.name)[0..5] AS via_entities,
                               count(DISTINCT shared) AS bridge_count
                        ORDER BY bridge_count DESC LIMIT $limit
                        """,
                        uid=uid,
                        keys=keys,
                        limit=limit,
                    )
                ).data()
                if hops >= 2
                else []
            )
        return {"seeds": seeds, "neighbors": neighbors, "bridges": bridges}

    async def find_interests_by_entity(
        self, *, user_id: uuid.UUID, terms: list[str], limit: int = 5
    ) -> list[dict]:
        """实体反查:问某个实体(CBA/库里)时,找到用户关注的相关实体。

        两种命中:① 该实体本身就是用户关注的;② 该实体是某个关注实体的邻居。
        """
        cleaned = [t.strip() for t in terms if t and t.strip()]
        if not cleaned:
            return []
        uid = str(user_id)
        direct_q = """
        MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(e:Entity)
        WHERE any(t IN $terms WHERE toLower(e.name) CONTAINS toLower(t) OR toLower(e.key) CONTAINS toLower(t))
        RETURN DISTINCT e.key AS key, e.name AS name, e.category AS category, e.type AS type,
               [] AS via
        LIMIT $limit
        """
        via_q = """
        MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(i:Entity)
        MATCH p = (i)-[:RELATED*1..2]-(m:Entity {user_id:$uid})
        WHERE any(t IN $terms WHERE toLower(m.name) CONTAINS toLower(t) OR toLower(m.key) CONTAINS toLower(t))
        RETURN i.key AS key, i.name AS name, i.category AS category, i.type AS type,
               collect(DISTINCT m.name)[0..3] AS via, min(length(p)) AS hops
        ORDER BY hops ASC
        LIMIT $limit
        """
        out: list[dict] = []
        seen: set[str] = set()
        async with neo4j_client.driver.session() as session:
            for query in (direct_q, via_q):
                rows = await (
                    await session.run(query, uid=uid, terms=cleaned, limit=limit)
                ).data()
                for row in rows:
                    if row["key"] in seen:
                        continue
                    seen.add(row["key"])
                    out.append(row)
        return out[:limit]

    async def shortest_path(
        self, *, user_id: uuid.UUID, a_key: str, b_key: str, max_hops: int = MAX_HOPS
    ) -> list[str] | None:
        """两个关注实体之间在实体图上的最短路"""
        hops = max(1, min(int(max_hops), MAX_HOPS))
        query = f"""
        MATCH (u:User {{id:$uid}})-[:INTERESTED_IN]->(a:Entity {{key:$a}}),
              (u)-[:INTERESTED_IN]->(b:Entity {{key:$b}})
        MATCH p = shortestPath((a)-[:RELATED*..{hops}]-(b))
        RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops
        LIMIT 1
        """
        async with neo4j_client.driver.session() as session:
            rows = await (await session.run(query, uid=str(user_id), a=a_key, b=b_key)).data()
        if not rows:
            return None
        return list(rows[0].get("path") or [])

    # ---------- Statement 溯源层 ----------
    async def upsert_statements(self, *, user_id: uuid.UUID, statements: list[dict]) -> int:
        """批量幂等写入 Statement 节点与 MENTIONS 边,返回写入条数"""
        if not statements:
            return 0
        uid = str(user_id)
        query = """
        UNWIND $statements AS st
        MERGE (s:Statement {user_id:$uid, sid:st.sid})
          SET s.text = st.text,
              s.occurred_at = coalesce(st.occurred_at, s.occurred_at),
              s.message_id = coalesce(st.message_id, s.message_id),
              s.conversation_id = coalesce(st.conversation_id, s.conversation_id)
        WITH s, st
        UNWIND st.entity_keys AS k
        MATCH (e:Entity {user_id:$uid, key:k})
        MERGE (s)-[:MENTIONS]->(e)
        """
        async with neo4j_client.driver.session() as session:
            await session.run(query, uid=uid, statements=statements)
        return len(statements)

    async def statements_for_entity(
        self, *, user_id: uuid.UUID, key: str, limit: int = 5
    ) -> list[dict]:
        """某实体出现在哪些原句里(按时间倒序)"""
        query = """
        MATCH (s:Statement {user_id:$uid})-[:MENTIONS]->(e:Entity {user_id:$uid, key:$key})
        RETURN s.text AS text, s.occurred_at AS occurred_at, s.message_id AS message_id
        ORDER BY s.occurred_at DESC
        LIMIT $limit
        """
        async with neo4j_client.driver.session() as session:
            rows = await (
                await session.run(query, uid=str(user_id), key=key, limit=limit)
            ).data()
        return rows or []
