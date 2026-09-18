"""兴趣抽取异步任务入口:独立 session,失败不阻塞聊天"""
import asyncio
import logging
from datetime import timezone

from ....db.postgres import async_session
from .extractor import extract_graph, should_extract
from .writer import write_extraction

logger = logging.getLogger(__name__)

# 抽取包含 1 轮补漏(2 次 LLM 调用) + embedding + 双写,20s 太紧;后台任务可以给宽一点
EXTRACT_TIMEOUT = 60


async def extract_and_store(
    user_id,
    text: str,
    conversation_id=None,
    message_id=None,
    occurred_at=None,
    context_messages=None,
) -> int:
    """聊天回复结束后后台运行;返回写入条数(失败返回 0)"""
    if not text:
        return 0
    if occurred_at is None:
        # 现场对话没有显式时间:用当前时间,保证提及与 Statement 都有时间锚点
        from datetime import datetime, timezone

        occurred_at = datetime.now(timezone.utc)
    try:
        async with async_session() as session:
            from ....repositories.interest_repository import InterestRepository

            known = [n.name for n in await InterestRepository(session).list_nodes(user_id, limit=200)]
            try:
                from .graph_repo import InterestGraphRepo

                graph_entities = await InterestGraphRepo().list_entities(user_id=user_id, limit=200)
                known = [str(e.get("name")) for e in graph_entities if e.get("name")] or known
            except Exception as e:  # noqa: BLE001
                logger.warning("load known entities failed: %s", e)
            if not should_extract(text, known):
                return 0
            from ....core.llm.client import build_chat_model
            from ....core.llm.resolver import get_default_config

            config = await get_default_config(session, user_id, "chat")
            model = build_chat_model(config, streaming=False, temperature=0)
            base_date = occurred_at.date() if occurred_at else None
            extraction = await asyncio.wait_for(
                extract_graph(
                    model,
                    text,
                    base_date,
                    known_entities=known,
                    context_messages=context_messages,
                ),
                timeout=EXTRACT_TIMEOUT,
            )
            if not extraction["entities"] and not extraction["relations"]:
                return 0
            written = await write_extraction(
                session,
                user_id,
                extraction,
                raw_text=text,
                conversation_id=conversation_id,
                message_id=message_id,
                occurred_at=occurred_at,
            )
            # 写入后刷新兴趣社区(只有成员/关系变化的社区才重新生成摘要)
            if written:
                try:
                    from .community import refresh_communities

                    await refresh_communities(session, user_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("refresh communities failed: %s", e)
            return written
    except asyncio.TimeoutError:
        logger.warning("interest extraction timeout")
    except Exception as e:  # noqa: BLE001
        logger.warning("interest extraction failed: %s", e)
    return 0


async def extract_batch_and_store(user_id, entries: list) -> int:
    """把一批连续消息合并成「一次」LLM 抽取,再按 evidence 归属回各自消息写库。

    与单条抽取的区别:① 只调一次模型;② 每条消息保留自己的 message_id 与时间;
    ③ 相对时间(最近/这阵子)按各自消息的时间解析,而不是整批用一个基准。
    """
    from datetime import date, datetime

    from .batch_utils import attribute_entities, build_batch_text, group_by_entry
    from .normalizer import parse_time_expr

    usable = []
    for raw in entries or []:
        text = (raw.get("text") or "").strip()
        if not text or not should_extract(text):
            continue
        item = dict(raw)
        when = item.get("occurred_at")
        if isinstance(when, str) and when:
            try:
                when = datetime.fromisoformat(when)
            except ValueError:
                when = None
        item["occurred_at"] = when or datetime.now(timezone.utc)
        usable.append(item)
    if not usable:
        return 0
    if len(usable) == 1:
        only = usable[0]
        return await extract_and_store(
            user_id,
            only["text"],
            conversation_id=only.get("conversation_id"),
            message_id=only.get("message_id"),
            occurred_at=only["occurred_at"],
        )

    try:
        async with async_session() as session:
            from ....core.llm.client import build_chat_model
            from ....core.llm.resolver import get_default_config
            from ....repositories.interest_repository import InterestRepository
            from .graph_repo import InterestGraphRepo

            known = [n.name for n in await InterestRepository(session).list_nodes(user_id, limit=200)]
            try:
                graph_entities = await InterestGraphRepo().list_entities(user_id=user_id, limit=200)
                known = [str(e.get("name")) for e in graph_entities if e.get("name")] or known
            except Exception as e:  # noqa: BLE001
                logger.warning("load known entities failed: %s", e)

            config = await get_default_config(session, user_id, "chat")
            model = build_chat_model(config, streaming=False, temperature=0)
            combined = build_batch_text(usable)
            extraction = await asyncio.wait_for(
                extract_graph(model, combined, None, known_entities=known, batch=True),
                timeout=EXTRACT_TIMEOUT,
            )
            entities, relations = extraction.get("entities") or [], extraction.get("relations") or []
            if not entities and not relations:
                return 0

            owners = attribute_entities(entities, usable)
            groups = group_by_entry(entities, relations, owners, usable)
            written = 0
            for bucket in groups:
                entry = bucket["entry"]
                entry_date = entry["occurred_at"].date()
                for entity in bucket["entities"]:
                    if entity.get("since") is None or entity.get("until") is None:
                        since, until = parse_time_expr(entry["text"], entry_date)
                        entity["since"] = entity.get("since") or since
                        entity["until"] = entity.get("until") or until
                written += await write_extraction(
                    session,
                    user_id,
                    {"entities": bucket["entities"], "relations": bucket["relations"]},
                    raw_text=entry["text"],
                    conversation_id=entry.get("conversation_id"),
                    message_id=entry.get("message_id"),
                    occurred_at=entry["occurred_at"],
                )
            if written:
                try:
                    from .community import refresh_communities

                    await refresh_communities(session, user_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("refresh communities failed: %s", e)
            logger.info("interest batch: %d 条消息 -> 1 次抽取,写入 %d", len(usable), written)
            return written
    except asyncio.TimeoutError:
        logger.warning("interest batch extraction timeout")
    except Exception as e:  # noqa: BLE001
        logger.warning("interest batch extraction failed: %s", e)
    return 0
