"""记忆检索入口:向量 + 关键词候选池,融合排序,命中回写。"""
import logging

from .ranking import fuse_score

logger = logging.getLogger(__name__)


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
