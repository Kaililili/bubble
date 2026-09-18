"""ToolConfig 数据访问层"""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.tool_config_model import ToolConfig


class ToolConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: UUID) -> list[ToolConfig]:
        result = await self.session.execute(
            select(ToolConfig).where(ToolConfig.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_by_key(self, user_id: UUID, tool_key: str) -> ToolConfig | None:
        result = await self.session.execute(
            select(ToolConfig).where(
                ToolConfig.user_id == user_id, ToolConfig.tool_key == tool_key
            )
        )
        return result.scalar_one_or_none()

    async def set_enabled(self, user_id: UUID, tool_key: str, enabled: bool) -> ToolConfig:
        config = await self.get_by_key(user_id, tool_key)
        if config:
            config.enabled = enabled
        else:
            config = ToolConfig(user_id=user_id, tool_key=tool_key, enabled=enabled)
            self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)
        return config
