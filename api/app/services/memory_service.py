"""记忆业务逻辑"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import AppException
from ..core.security import decrypt_secret
from ..repositories.memory_repository import MemoryRepository, UserProfileRepository


class MemoryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.profiles = UserProfileRepository(session)
        self.memories = MemoryRepository(session)

    async def list_profiles(self, user_id: UUID):
        return await self.profiles.list_by_user(user_id)

    async def upsert_profile(self, user_id: UUID, key: str, value: str, importance: int):
        return await self.profiles.upsert(user_id, key, value, importance)

    async def delete_profile(self, user_id: UUID, profile_id: UUID):
        profile = await self.profiles.get_by_id(profile_id, user_id)
        if not profile:
            raise AppException(code=404, message="用户背景不存在")
        await self.profiles.delete(profile)

    async def upsert_credential(self, user_id: UUID, key: str, value: str) -> str:
        """面板表单写入/更新凭证:按归一化应用 key 覆盖,复用 remember 的加密/脱敏/embedding 逻辑。"""
        from ..core.agent.tools.base import ToolContext
        from ..core.agent.tools.builtin.memory_tools import remember
        from ..core.security import credential_key

        norm_key = credential_key(f"{key} 密码") or key.strip()
        if not norm_key:
            raise AppException(code=400, message="凭证归属(key)不能为空")
        ctx = ToolContext(self.session, user_id)
        result = await remember(ctx, content=f"{norm_key} 密码 {value}", type="credential")
        if not result.startswith(("已记住", "已更新")):
            raise AppException(code=400, message=result)
        return result

    async def list_memories(self, user_id: UUID, type: str | None = None, keyword: str | None = None):
        return await self.memories.list_by_user(user_id, type, keyword)

    async def delete_memory(self, user_id: UUID, memory_id: UUID):
        memory = await self.memories.get_by_id(memory_id, user_id)
        if not memory:
            raise AppException(code=404, message="记忆不存在")
        await self.memories.delete(memory)

    async def reveal_memory(self, user_id: UUID, memory_id: UUID) -> str:
        memory = await self.memories.get_by_id(memory_id, user_id)
        if not memory:
            raise AppException(code=404, message="记忆不存在")
        if memory.type != "credential" or not memory.content_encrypted:
            return memory.content
        return decrypt_secret(memory.content_encrypted)
