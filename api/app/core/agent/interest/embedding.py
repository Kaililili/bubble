"""兴趣模块共用的 embedding 构建:未配置时返回 None,调用方降级关键词"""


async def build_embedder(session, user_id):
    from ....core.llm.embedding import build_embedding_model
    from ....core.llm.resolver import get_default_config

    try:
        config = await get_default_config(session, user_id, "embedding")
        return build_embedding_model(config)
    except Exception:  # noqa: BLE001
        return None


async def embed_names(embedder, items: list) -> dict:
    """批量算向量:items=[(key, text)] -> {key: vector}。

    一次 embed_documents 调用完成(而不是每个文本一次网络往返);
    批量失败时回退逐条,单条失败只跳过该条,不影响其它。
    """
    if embedder is None or not items:
        return {}
    keys = [k for k, _ in items]
    texts = [t for _, t in items]
    try:
        vectors = await embedder.aembed_documents(texts)
        return {k: v for k, v in zip(keys, vectors)}
    except Exception:  # noqa: BLE001
        out = {}
        for k, text in items:
            try:
                out[k] = await embedder.aembed_query(text)
            except Exception:  # noqa: BLE001
                continue
        return out
