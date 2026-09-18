"""数据库结构自举:建 pgvector 扩展、建缺失的表、补列、建向量索引(全部幂等)。

应用启动时会自动执行,所以用户 clone 下来直接起服务就能用,不需要手动建库;
init_db.py 是同逻辑的手动入口(CI/排障用)。
"""
import logging

from sqlalchemy import text

from .postgres import engine

logger = logging.getLogger(__name__)

# 已存在的表补列(create_all 不会给已有表加列)
ALTER_STATEMENTS = (
    "ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS sensitive_tools JSONB",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_until_message_id UUID",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'active'",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by UUID",
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS valid_at TIMESTAMPTZ",
    "ALTER TABLE interest_nodes ADD COLUMN IF NOT EXISTS entity_type VARCHAR(32)",
)

# 向量索引(pgvector HNSW:近似最近邻,避免全表扫描)
HNSW_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_interest_nodes_embedding_hnsw "
    "ON interest_nodes USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw "
    "ON memories USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS idx_insight_embedding_hnsw "
    "ON memory_insights USING hnsw (embedding vector_cosine_ops)",
)


def _load_models() -> None:
    """显式导入所有模型,确保 Base.metadata 里有全部表定义"""
    from ..models import (  # noqa: F401
        conversation_model,
        emotion_model,
        interest_community_model,
        interest_model,
        mcp_server_model,
        memory_insight_model,
        memory_model,
        model_config_model,
        tool_approval_model,
        tool_config_model,
        user_model,
    )


async def ensure_schema() -> None:
    """幂等建表/补列/建索引;可重复执行,已存在时几乎无开销"""
    from ..db import Base

    _load_models()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in ALTER_STATEMENTS:
            await conn.execute(text(stmt))
        for stmt in HNSW_INDEXES:
            await conn.execute(text(stmt))
    logger.info("数据库结构已就绪(建表/补列/索引,幂等)")
