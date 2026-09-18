"""模型配置业务逻辑"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.llm.provider import PROVIDER_DEFAULT_BASE_URL, test_connection
from ..core.security import encrypt_secret
from ..core.exceptions import AppException
from ..repositories.model_config_repository import ModelConfigRepository


class ModelConfigService:
    def __init__(self, session: AsyncSession):
        self.repo = ModelConfigRepository(session)

    async def list(self, user_id: UUID):
        return await self.repo.list_by_user(user_id)

    async def create(self, user_id: UUID, payload):
        base_url = (payload.base_url or "").strip() or PROVIDER_DEFAULT_BASE_URL.get(payload.provider, "")
        if not base_url:
            raise AppException(code=400, message="请填写 base_url 或选择已知 provider")
        if payload.is_default:
            await self.repo.clear_default(user_id, payload.model_type)
        return await self.repo.create(
            user_id=user_id,
            model_type=payload.model_type,
            provider=payload.provider,
            model_name=payload.model_name,
            api_key_encrypted=encrypt_secret(payload.api_key),
            supports_function_call=payload.supports_function_call,
            base_url=base_url,
            is_default=payload.is_default,
        )

    async def update(self, user_id: UUID, config_id: UUID, payload):
        config = await self.repo.get_by_id(config_id, user_id)
        if not config:
            raise AppException(code=404, message="模型配置不存在")
        if payload.is_default:
            await self.repo.clear_default(user_id, payload.model_type or config.model_type)
        data = payload.model_dump(exclude_unset=True)
        if "api_key" in data and data["api_key"] is not None:
            data["api_key_encrypted"] = encrypt_secret(data.pop("api_key"))
        if "base_url" in data and data["base_url"] is not None:
            data["base_url"] = data["base_url"].strip() or config.base_url
        return await self.repo.update(config, data)

    async def delete(self, user_id: UUID, config_id: UUID):
        config = await self.repo.get_by_id(config_id, user_id)
        if not config:
            raise AppException(code=404, message="模型配置不存在")
        await self.repo.delete(config)
