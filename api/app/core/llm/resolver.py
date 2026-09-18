"""按用户类型解析默认模型配置"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from ...models.model_config_model import ModelConfig
from ...repositories.model_config_repository import ModelConfigRepository
from ..exceptions import AppException

_TYPE_LABEL = {"chat": "对话", "embedding": "Embedding", "rerank": "Rerank"}


async def get_default_config(
    session: AsyncSession, user_id: uuid.UUID, model_type: str = "chat"
) -> ModelConfig:
    """取用户某类型的默认模型配置,无默认则取第一个,都没有则报错"""
    configs = await ModelConfigRepository(session).list_by_user(user_id, model_type=model_type)
    if not configs:
        label = _TYPE_LABEL.get(model_type, model_type)
        raise AppException(code=400, message=f"未配置{label}模型,请先在 设置-模型配置 中添加")
    return next((c for c in configs if c.is_default), configs[0])
