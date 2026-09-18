"""实体合并:图(搬关注边/关系边) + PG(迁移提及/合并时间计数)"""
import logging

from .graph_repo import InterestGraphRepo

logger = logging.getLogger(__name__)


async def merge_entities_full(session, user_id, keep_key: str, drop_key: str) -> bool:
    """把 drop 合并进 keep;图先合并,成功后再合并 PG(避免半成品)"""
    if not keep_key or not drop_key or keep_key == drop_key:
        return False
    graph_ok = await InterestGraphRepo().merge_entities(
        user_id=user_id, keep_key=keep_key, drop_key=drop_key
    )
    if not graph_ok:
        return False
    try:
        from ....repositories.interest_repository import InterestRepository

        await InterestRepository(session).merge_into(user_id, keep_key, drop_key)
    except Exception as e:  # noqa: BLE001
        logger.warning("pg merge failed (%s -> %s): %s", drop_key, keep_key, e)
    return True
