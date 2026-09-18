"""MCP server 配置数据访问层"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.mcp_server_model import MCPServer


class MCPServerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: UUID, enabled_only: bool = False) -> list[MCPServer]:
        stmt = select(MCPServer).where(MCPServer.user_id == user_id)
        if enabled_only:
            stmt = stmt.where(MCPServer.enabled.is_(True))
        stmt = stmt.order_by(MCPServer.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, server_id: UUID, user_id: UUID) -> MCPServer | None:
        result = await self.session.execute(
            select(MCPServer).where(MCPServer.id == server_id, MCPServer.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(self, server: MCPServer) -> MCPServer:
        self.session.add(server)
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def update(self, server: MCPServer) -> MCPServer:
        await self.session.commit()
        await self.session.refresh(server)
        return server

    async def delete(self, server: MCPServer) -> None:
        await self.session.delete(server)
        await self.session.commit()

    async def mark_status(self, server: MCPServer, status: str, last_error: str | None = None) -> MCPServer:
        """更新连接状态(测试连接/同步时用;不要在每轮工具加载失败时调用,避免污染缓存指纹)。"""
        server.status = status
        server.last_error = last_error
        await self.session.commit()
        await self.session.refresh(server)
        return server
