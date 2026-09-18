"""工具管理业务逻辑"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.agent.tools import REGISTRY, _tool_configured
from ..core.exceptions import AppException
from ..repositories.tool_config_repository import ToolConfigRepository


class ToolService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ToolConfigRepository(session)

    async def list(self, user_id: UUID) -> list[dict]:
        """列出所有内置工具及当前用户的启停/配置状态"""
        rows = await self.repo.list_by_user(user_id)
        user_set = {r.tool_key: r.enabled for r in rows}
        result = []
        for key, spec in REGISTRY.items():
            configured = True
            if spec.needs_config:
                configured = await _tool_configured(self.session, user_id, key)
            result.append(
                {
                    "key": key,
                    "name": key,
                    "description": spec.description,
                    "enabled": user_set.get(key, spec.default_enabled),
                    "needs_config": spec.needs_config,
                    "configured": configured,
                    "default_enabled": spec.default_enabled,
                }
            )
        return result

    async def set_enabled(self, user_id: UUID, tool_key: str, enabled: bool):
        if tool_key not in REGISTRY:
            raise AppException(code=404, message=f"工具不存在:{tool_key}")
        return await self.repo.set_enabled(user_id, tool_key, enabled)
