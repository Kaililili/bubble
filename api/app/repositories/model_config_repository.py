"""ModelConfig 数据访问层"""
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.model_config_model import ModelConfig


class ModelConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: UUID, model_type: str | None = None) -> list[ModelConfig]:
        """查询用户模型配置(可按类型过滤)"""
        stmt = select(ModelConfig).where(ModelConfig.user_id == user_id).order_by(ModelConfig.created_at)
        if model_type:
            stmt = stmt.where(ModelConfig.model_type == model_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, config_id: UUID, user_id: UUID) -> ModelConfig | None:
        """按 ID 查询(限定用户)"""
        result = await self.session.execute(
            select(ModelConfig).where(ModelConfig.id == config_id, ModelConfig.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def clear_default(self, user_id: UUID, model_type: str) -> None:
        """清除某类型下所有默认标记"""
        await self.session.execute(
            update(ModelConfig)
            .where(ModelConfig.user_id == user_id, ModelConfig.model_type == model_type)
            .values(is_default=False)
        )

    async def create(
        self,
        *,
        user_id: UUID,
        model_type: str,
        provider: str,
        model_name: str,
        api_key_encrypted: str,
        base_url: str,
        supports_function_call: bool = True,
        is_default: bool,
    ) -> ModelConfig:
        config = ModelConfig(
            user_id=user_id,
            model_type=model_type,
            provider=provider,
            model_name=model_name,
            api_key_encrypted=api_key_encrypted,
            base_url=base_url,
            supports_function_call=supports_function_call,
            is_default=is_default,
        )
        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def update(self, config: ModelConfig, data: dict) -> ModelConfig:
        """更新字段并提交"""
        for key, value in data.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        await self.session.commit()
        await self.session.refresh(config)
        return config

    async def delete(self, config: ModelConfig) -> None:
        await self.session.delete(config)
        await self.session.commit()
