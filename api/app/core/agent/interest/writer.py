"""图谱写入编排:PG(关注实体物化索引 + 向量 + 提及) → Neo4j(Entity + INTERESTED_IN + RELATED)"""
import logging

from .embedding import build_embedder, embed_names
from .graph_repo import InterestGraphRepo
from .normalizer import dedup_key
from .merger import merge_entities_full
from .resolver import audit_duplicate_groups, semantic_canonical

# O3:审计去抖 —— 自上次审计以来累计新增实体达到该数量才跑整表审计
AUDIT_MIN_NEW_ENTITIES = 3
# 每个新增实体最多带几个向量邻居进审计(不再把整张实体表发过去)
AUDIT_NEIGHBORS = 3

logger = logging.getLogger(__name__)


async def write_extraction(
    session,
    user_id,
    extraction: dict,
    raw_text: str = "",
    conversation_id=None,
    message_id=None,
    occurred_at=None,
) -> int:
    """写入一轮抽取结果;返回写入的"关注实体"条数。

    只有 is_followed=true 的实体进 PG(面板/时间线/向量检索);
    其余实体只进图(作为实体节点),用于关系与多跳。
    """
    from ....repositories.interest_repository import InterestRepository

    entities = extraction.get("entities") or []
    relations = extraction.get("relations") or []
    if not entities and not relations:
        return 0

    repo = InterestRepository(session)
    graph = InterestGraphRepo()
    embedder = await build_embedder(session, user_id)

    # O1:一次批量算好「实体名」与「展示名(name(category))」两套向量,避免逐条调用与重复计算
    embed_items = []
    for _entity in entities:
        _name = _entity.get("name") or _entity.get("key") or ""
        if not _name:
            continue
        embed_items.append(("name::" + _name, _name))
        _cat = _entity.get("category") or "其他"
        embed_items.append(("disp::" + _name, f"{_name}({_cat})"))
    vec_map = await embed_names(embedder, embed_items)

    # 实体消解:把本次抽到的实体映射到已有实体(确定性规则:归一化 + 剥离通用修饰词)
    try:
        existing_entities = await graph.list_entities(user_id=user_id, limit=500)
    except Exception as e:  # noqa: BLE001
        logger.warning("list_entities failed, skip canonicalization: %s", e)
        existing_entities = []
    dedup_index: dict[str, dict] = {}
    for item in existing_entities:
        dk = dedup_key(item.get("name") or item.get("key") or "")
        if dk:
            dedup_index.setdefault(dk, item)
    canonical: dict[str, tuple[str, str]] = {}
    judge_model = None
    for entity in entities:
        key, name = entity.get("key"), entity.get("name") or entity.get("key")
        if not key:
            continue
        hit = dedup_index.get(dedup_key(name or key))
        if not hit and embedder is not None:
            # 第三层:向量找候选 + LLM 裁决(处理"检索项目"与"RAG"这类不同说法)
            if judge_model is None:
                try:
                    from ....core.llm.client import build_chat_model
                    from ....core.llm.resolver import get_default_config

                    config = await get_default_config(session, user_id, "chat")
                    judge_model = build_chat_model(config, streaming=False, temperature=0)
                except Exception as e:  # noqa: BLE001
                    logger.warning("judge model unavailable: %s", e)
                    judge_model = False  # type: ignore[assignment]
            semantic = await semantic_canonical(
                session,
                user_id,
                name or key,
                embedder=embedder,
                judge_model=judge_model or None,
                vector=vec_map.get("name::" + (name or key)),
            )
            if semantic:
                hit = {"key": semantic[0], "name": semantic[1]}
        if hit and hit.get("key") and hit["key"] != key:
            canonical[key] = (hit["key"], hit.get("name") or hit["key"])
        else:
            canonical[key] = (key, name or key)
            if dedup_key(name or key):
                dedup_index.setdefault(dedup_key(name or key), {"key": key, "name": name})

    def canon_key(value: str | None) -> str | None:
        if not value:
            return value
        return canonical.get(value, (value, value))[0]

    followed_nodes: dict[str, object] = {}
    # 已关注的实体在后续句子里再次出现(哪怕模型判 is_followed=false,例如"咖啡喝得少了")
    # 也要更新提及与时间,否则结束时间/冷却状态会丢
    entity_keys = [canon_key(e.get("key")) for e in entities if e.get("key")]
    existing = {n.key: n for n in await repo.list_by_keys(user_id, entity_keys)}
    for entity in entities:
        raw_key = entity.get("key")
        if not raw_key:
            continue
        key, name = canonical.get(raw_key, (raw_key, entity.get("name") or raw_key))
        if not entity.get("is_followed") and key not in existing:
            continue
        category = entity.get("category") or "其他"
        embedding = vec_map.get("disp::" + (name or ""))
        node, _created = await repo.upsert_node(
            user_id=user_id,
            key=key,
            name=name,
            category=category,
            entity_type=entity.get("type"),
            aliases=entity.get("aliases") or [],
            embedding=embedding,
            since=entity.get("since"),
            until=entity.get("until"),
            last_seen=occurred_at,
            revive=bool(entity.get("is_followed")),
        )
        followed_nodes[key] = node
        await repo.add_mention(
            user_id=user_id,
            interest_id=node.id,
            raw_text=entity.get("evidence") or raw_text,
            since=entity.get("since"),
            until=entity.get("until"),
            confidence=float(entity.get("confidence") or 0.0),
            conversation_id=conversation_id,
            message_id=message_id,
            created_at=occurred_at,
        )

    graph_entities = []
    for entity in entities:
        raw_key = entity.get("key")
        if not raw_key:
            continue
        key, name = canonical.get(raw_key, (raw_key, entity.get("name") or raw_key))
        node = followed_nodes.get(key)
        graph_entities.append(
            {
                "key": key,
                "name": name or key,
                "type": entity.get("type"),
                "category": entity.get("category"),
                "description": entity.get("description"),
                "aliases": entity.get("aliases") or [],
                "is_followed": bool(entity.get("is_followed")),
                "since": entity["since"].isoformat() if entity.get("since") else None,
                "until": entity["until"].isoformat() if entity.get("until") else None,
                # 重新关注时清掉旧的结束时间
                "clear_until": bool(node is not None and getattr(node, "until", None) is None),
                "status": getattr(node, "status", None),
            }
        )
    graph_relations = [
        {
            "from_key": canon_key(rel.get("from_key")),
            "to_key": canon_key(rel.get("to_key")),
            "type": rel.get("type") or "related",
            "description": rel.get("evidence"),
        }
        for rel in relations
    ]

    try:
        await graph.upsert_graph(user_id=user_id, entities=graph_entities, relations=graph_relations)
        for node in followed_nodes.values():
            await repo.mark_graph_synced(node, True)
        # Statement 溯源层:复用抽取阶段已通过接地校验的 evidence,不额外调用模型
        try:
            from .statements import build_statements

            statements = build_statements(
                entities,
                relations,
                raw_text=raw_text,
                occurred_at=occurred_at,
                message_id=message_id,
                conversation_id=conversation_id,
                canon=canon_key,
            )
            await graph.upsert_statements(user_id=user_id, statements=statements)
        except Exception as e:  # noqa: BLE001
            logger.warning("statement upsert failed (needs rebuild): %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("interest graph write failed (needs rebuild): %s", e)
        for node in followed_nodes.values():
            await repo.mark_graph_synced(node, False)

    # 语义去重:整表 LLM 审计(一次调用),把"同一概念的不同说法"合并
    try:
        if judge_model is None:
            from ....core.llm.client import build_chat_model
            from ....core.llm.resolver import get_default_config

            config = await get_default_config(session, user_id, "chat")
            judge_model = build_chat_model(config, streaming=False, temperature=0)
        if judge_model:
            # 只统计「图谱里原本没有」的实体:重复提到已知实体不该触发审计
            existing_keys = {e.get("key") for e in existing_entities}
            known_dedup = set(dedup_index)
            new_names = [
                e.get("name")
                for e in entities
                if e.get("name")
                and e.get("key") not in existing_keys
                and dedup_key(e.get("name") or "") not in known_dedup
            ]
            if await _should_audit(user_id, new_names):
                audit_names = await _audit_candidates(session, user_id, new_names, vec_map)
                current = await graph.list_entities(user_id=user_id, limit=200)
                groups = await audit_duplicate_groups(judge_model, audit_names)
            else:
                groups = []
            by_name = {e["name"]: e for e in current} if groups else {}
            for group in groups:
                members = [by_name[n] for n in group if n in by_name]
                members.sort(key=lambda m: (not m.get("followed"), len(m["name"]), m["name"]))
                if len(members) < 2:
                    continue
                keep = members[0]
                for drop in members[1:]:
                    ok = await merge_entities_full(session, user_id, keep["key"], drop["key"])
                    if ok:
                        logger.info("merged duplicate entity %s -> %s", drop["name"], keep["name"])
    except Exception as e:  # noqa: BLE001
        logger.warning("entity audit/dedup failed: %s", e)
    return len(followed_nodes)


async def _should_audit(user_id, new_names: list) -> bool:
    """审计去抖:累计新增实体够多才审计(Redis 计数;无 Redis 时按本轮新增判断)"""
    added = len([n for n in new_names if n])
    if added == 0:
        return False
    try:
        from ....db.redis import get_redis

        redis = await get_redis()
        key = f"interest:audit:pending:{user_id}"
        pending = await redis.incrby(key, added)
        if pending >= AUDIT_MIN_NEW_ENTITIES:
            await redis.set(key, 0)
            return True
        return False
    except Exception:  # noqa: BLE001
        return added >= AUDIT_MIN_NEW_ENTITIES


async def _audit_candidates(session, user_id, new_names: list, vec_map: dict) -> list:
    """审计输入 = 本轮新增实体 + 它们的向量近邻(把输入规模从"全表"降到常数级)"""
    from ....repositories.interest_repository import InterestRepository

    names = {n for n in new_names if n}
    repo = InterestRepository(session)
    if not vec_map:
        return sorted(names)
    for name in list(names):
        vector = vec_map.get("name::" + name)
        if not vector:
            continue
        try:
            for node, _sim in await repo.search_by_vector(user_id, vector, top_k=AUDIT_NEIGHBORS):
                names.add(node.name)
        except Exception:  # noqa: BLE001
            continue
    return sorted(names)
