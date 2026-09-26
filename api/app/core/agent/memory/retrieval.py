"""记忆检索入口:向量 + 关键词候选池,融合排序,命中回写。"""
import logging

from .ranking import fuse_score

logger = logging.getLogger(__name__)

# 记忆来源 → 给模型看的说明;系统概括不能冒充用户原话
SOURCE_LABELS = {
    "chat": "用户对话原话",
    "review": "系统生成的个人回顾",
    "insight": "系统概括",
    "manual": "用户手动添加",
    "import": "导入数据",
}
STATUS_LABELS = {"active": "现行", "superseded": "已失效"}


async def search_memories(session, user_id, query: str, *, limit: int = 6, touch: bool = True):
    """融合检索:未配 embedding 时降级关键词,失败返回空列表不抛错。"""
    from app.core.llm.embedding import build_embedding_model
    from app.core.llm.resolver import get_default_config
    from app.repositories.memory_repository import MemoryRepository

    repo = MemoryRepository(session)
    vector = None
    try:
        config = await get_default_config(session, user_id, "embedding")
        embedder = build_embedding_model(config)
        vector = await embedder.aembed_query((query or "")[:500])
    except Exception:  # noqa: BLE001
        vector = None

    try:
        candidates = await repo.search_candidates(user_id, vector, query, limit=20)
    except Exception as e:  # noqa: BLE001
        logger.warning("memory search failed: %s", e)
        return []
    if not candidates:
        return []

    scored = [
        (
            memory,
            fuse_score(
                similarity,
                memory.importance,
                memory.last_accessed_at or memory.created_at,
            ),
        )
        for memory, similarity in candidates
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    top = [memory for memory, _score in scored[:limit]]
    if touch:
        try:
            await repo.touch_accessed(top)
        except Exception as e:  # noqa: BLE001
            logger.warning("memory touch failed: %s", e)
    return top


async def build_memory_evidence(session, memories: list) -> list[dict]:
    """把检索到的记忆补成"可追溯证据"(批量取来源消息,一次查询)。

    凭证类只给脱敏描述,不回指原话;旧数据没有来源时如实标"来源未知"。
    """
    from sqlalchemy import select

    from app.models.conversation_model import Message

    ids = [m.source_message_id for m in memories if getattr(m, "source_message_id", None)]
    quotes: dict = {}
    if ids:
        try:
            rows = (
                await session.execute(select(Message).where(Message.id.in_(ids)))
            ).scalars().all()
            quotes = {row.id: row for row in rows}
        except Exception as exc:  # noqa: BLE001
            logger.warning("load memory source messages failed: %s", exc)

    items: list[dict] = []
    for memory in memories:
        source = getattr(memory, "source", None)
        source_message_id = getattr(memory, "source_message_id", None)
        quote = None
        quote_at = None
        if source_message_id and memory.type != "credential":
            message = quotes.get(source_message_id)
            if message is not None:
                quote = (message.content or "").strip()[:120]
                quote_at = message.created_at.strftime("%Y-%m-%d %H:%M") if message.created_at else None
        items.append(
            {
                "memory_id": str(memory.id),
                "type": memory.type,
                "content": memory.content,
                "status": memory.status,
                "status_label": STATUS_LABELS.get(memory.status, memory.status or "未知"),
                "source": source,
                "source_label": SOURCE_LABELS.get(source or "", ""),
                "source_message_id": str(source_message_id) if source_message_id else None,
                "quote": quote,
                "quote_at": quote_at,
                "created_at": memory.created_at.strftime("%Y-%m-%d %H:%M") if memory.created_at else None,
            }
        )
    return items


async def search_memory_evidence(session, user_id, query: str, *, limit: int = 6) -> list[dict]:
    """检索 + 证据补全(recall 工具用);检索语义与 search_memories 完全一致。"""
    memories = await search_memories(session, user_id, query, limit=limit)
    if not memories:
        return []
    return await build_memory_evidence(session, memories)


def render_memory_evidence(items: list[dict]) -> str:
    """把证据条目渲染成给模型看的紧凑文本(纯函数,便于单测/稳定输出格式)"""
    lines: list[str] = []
    for item in items:
        memory_id = str(item.get("memory_id") or "")
        meta = [
            f"记忆ID {memory_id[:8] or '未知'}",
            f"状态 {item.get('status_label') or '未知'}",
        ]
        if item.get("quote"):
            at = item.get("quote_at") or ""
            meta.append(f"来源 用户原话{(' ' + at) if at else ''}:\"{item['quote']}\"")
        else:
            label = item.get("source_label") or ""
            if item.get("type") == "credential":
                # 凭证永远不冒充"用户原话"来源,也不回指原文
                label = "凭证(已脱敏,不展示原话)"
            meta.append(f"来源 {label or '未知'}")
        lines.append(f"[{item.get('type')}] {item.get('content')}\n  (" + ";".join(meta) + ")")
    if not lines:
        return "没有检索到相关记忆。"
    header = f"检索到 {len(lines)} 条现行记忆(引用个人事实时请带上 记忆ID+时间):"
    return header + "\n" + "\n".join(lines)
