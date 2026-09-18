"""MCP server 业务:配置 CRUD + 测试连接 + 工具清单 + 瑞幸比价"""
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import AppException
from ..core.security import encrypt_secret
from ..models.mcp_server_model import STATUS_ERROR, STATUS_OK, MCPServer
from ..repositories.mcp_server_repository import MCPServerRepository
from ..schemas.mcp_schema import MCPServerCreate, MCPServerUpdate


class MCPService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MCPServerRepository(session)

    async def list_servers(self, user_id: UUID) -> list[MCPServer]:
        return await self.repo.list_by_user(user_id)

    async def _get_owned(self, user_id: UUID, server_id: UUID) -> MCPServer:
        server = await self.repo.get_by_id(server_id, user_id)
        if not server:
            raise AppException(code=404, message="MCP 配置不存在")
        return server

    async def create_server(self, user_id: UUID, body: MCPServerCreate) -> MCPServer:
        from ..core.agent.tools.mcp.loader import invalidate_mcp_cache

        server = MCPServer(
            user_id=user_id,
            name=body.name.strip(),
            transport=body.transport,
            url=body.url.strip(),
            token_encrypted=encrypt_secret(body.token) if body.token else None,
            allowed_tools=body.allowed_tools,
        )
        try:
            server = await self.repo.create(server)
        except IntegrityError:
            raise AppException(code=400, message=f"已存在名为 {body.name} 的 MCP 配置")
        invalidate_mcp_cache(user_id)
        return server

    async def update_server(
        self, user_id: UUID, server_id: UUID, body: MCPServerUpdate
    ) -> MCPServer:
        from ..core.agent.tools.mcp.loader import invalidate_mcp_cache

        server = await self._get_owned(user_id, server_id)
        if body.name is not None:
            server.name = body.name.strip()
        if body.transport is not None:
            server.transport = body.transport
        if body.url is not None:
            server.url = body.url.strip()
        if body.token:
            # token 留空 = 保留原值,避免空串覆盖
            server.token_encrypted = encrypt_secret(body.token)
        if body.enabled is not None:
            server.enabled = body.enabled
        if body.allowed_tools is not None:
            server.allowed_tools = body.allowed_tools
        if body.sensitive_tools is not None:
            server.sensitive_tools = body.sensitive_tools
        server.status = "unknown"
        server.last_error = None
        try:
            server = await self.repo.update(server)
        except IntegrityError:
            raise AppException(code=400, message=f"已存在名为 {server.name} 的 MCP 配置")
        invalidate_mcp_cache(user_id)
        return server

    async def delete_server(self, user_id: UUID, server_id: UUID) -> None:
        from ..core.agent.tools.mcp.loader import invalidate_mcp_cache

        server = await self._get_owned(user_id, server_id)
        await self.repo.delete(server)
        invalidate_mcp_cache(user_id)

    async def test_server(self, user_id: UUID, server_id: UUID) -> dict:
        """测试连接:握手 + 拉工具清单,成功即自动写入 tools_cache。"""
        from ..core.agent.tools.mcp.loader import (
            fetch_tools_meta,
            invalidate_mcp_cache,
        )

        server = await self._get_owned(user_id, server_id)
        try:
            meta = await fetch_tools_meta(server)
        except Exception as e:  # noqa: BLE001
            await self.repo.mark_status(server, STATUS_ERROR, f"连接失败: {e}")
            invalidate_mcp_cache(user_id)
            raise AppException(code=400, message=f"连接失败: {e}")
        server.tools_cache = meta
        server.synced_at = datetime.now()
        await self.repo.mark_status(server, STATUS_OK)
        invalidate_mcp_cache(user_id)
        return {"count": len(meta), "tools": meta}

    async def get_server_tools(self, user_id: UUID, server_id: UUID) -> list[dict]:
        server = await self._get_owned(user_id, server_id)
        return server.tools_cache or []

    async def compare_luckin(
        self,
        user_id: UUID,
        keyword: str,
        longitude: float | None = None,
        latitude: float | None = None,
    ) -> list[dict]:
        """瑞幸比价(瑞幸页确定性入口),复用 luckin_compare 聚合逻辑。"""
        from ..core.agent.tools.mcp.luckin_compare import run_luckin_compare

        items = await run_luckin_compare(
            self.session, user_id, keyword, longitude, latitude
        )
        if items and "error" in items[0]:
            raise AppException(code=400, message=items[0]["error"])
        return items

    async def preview_order(
        self,
        user_id: UUID,
        dept_id: int,
        product_id: int,
        amount: int = 1,
        specs: list[dict] | None = None,
    ) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_preview

        result = await run_order_preview(
            self.session, user_id, dept_id, product_id, amount, specs
        )
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        return result

    async def order_options(
        self, user_id: UUID, dept_id: int, product_id: int
    ) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_options

        result = await run_order_options(self.session, user_id, dept_id, product_id)
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        return result

    async def create_order(
        self,
        user_id: UUID,
        dept_id: int,
        product_id: int,
        amount: int = 1,
        sku_code: str | None = None,
        remark: str = "",
    ) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_create

        result = await run_order_create(
            self.session,
            user_id,
            dept_id,
            product_id,
            amount,
            remark,
            sku_code,
        )
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        return result

    async def cancel_order(self, user_id: UUID, order_id: str) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_cancel

        result = await run_order_cancel(self.session, user_id, order_id)
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        return result

    async def query_order(self, user_id: UUID, order_id: str) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_query

        result = await run_order_query(self.session, user_id, order_id)
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        return result

    # ── 敏感工具审批(通用确认机制) ──

    async def list_approvals(
        self, user_id: UUID, status: str | None = "pending"
    ) -> list:
        from sqlalchemy import select

        from ..models.tool_approval_model import ToolApproval

        stmt = select(ToolApproval).where(ToolApproval.user_id == user_id)
        if status:
            stmt = stmt.where(ToolApproval.status == status)
        stmt = stmt.order_by(ToolApproval.created_at.desc()).limit(50)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _get_approval(self, user_id: UUID, approval_id: UUID):
        from ..models.tool_approval_model import APPROVAL_PENDING, ToolApproval

        approval = await self.session.get(ToolApproval, approval_id)
        if approval is None or approval.user_id != user_id:
            raise AppException(code=404, message="确认请求不存在")
        if approval.status != APPROVAL_PENDING:
            raise AppException(code=400, message=f"该请求已处理({approval.status})")
        return approval

    async def approve_tool(
        self, user_id: UUID, approval_id: UUID, remember: bool = False
    ) -> dict:
        """确认执行:校验归属/状态/有效期 → 用后端保存的参数真正调用 MCP 工具。"""
        from datetime import datetime, timedelta, timezone

        from ..core.agent.tools.mcp.loader import execute_mcp_tool
        from ..models.tool_approval_model import (
            APPROVAL_EXECUTED,
            APPROVAL_EXPIRED,
            APPROVAL_FAILED,
        )

        approval = await self._get_approval(user_id, approval_id)
        created = approval.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created > timedelta(minutes=15):
                approval.status = APPROVAL_EXPIRED
                await self.session.commit()
                raise AppException(code=400, message="确认请求已过期,请重新发起")
        try:
            result = await execute_mcp_tool(
                self.session, approval.server_id, approval.tool_name, approval.args or {}
            )
            approval.status = APPROVAL_EXECUTED
            approval.result = (result or "")[:8000]
            approval.error = None
        except Exception as e:  # noqa: BLE001
            approval.status = APPROVAL_FAILED
            approval.error = str(e)[:1000]
        await self.session.commit()
        await self.session.refresh(approval)
        if remember:
            await self._remember_tool_safe(user_id, approval)
        return {
            "id": str(approval.id),
            "status": approval.status,
            "result": approval.result,
            "error": approval.error,
        }

    async def _remember_tool_safe(self, user_id: UUID, approval) -> None:
        """把该工具从 sensitive_tools 移除(以后免确认),并让工具缓存失效。"""
        from datetime import datetime, timezone

        from ..core.agent.tools.mcp.loader import (
            _annotations_map,
            _classify_tool,
            invalidate_mcp_cache,
        )
        from ..models.mcp_server_model import MCPServer

        server = await self.session.get(MCPServer, approval.server_id)
        if server is None:
            return
        current = server.sensitive_tools
        if current is None:
            # 未显式配置:先按默认规则推导出当前敏感集合,再移除该工具
            ann_map = _annotations_map(server)
            current = [
                t.get("name", "")
                for t in (server.tools_cache or [])
                if t.get("name")
                and _classify_tool(server, t["name"], ann_map.get(t["name"])) == "sensitive"
            ]
        target = approval.tool_name.lower()
        server.sensitive_tools = [x for x in current if str(x).lower() != target]
        server.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        invalidate_mcp_cache(user_id)

    async def reject_tool(self, user_id: UUID, approval_id: UUID) -> dict:
        from ..models.tool_approval_model import APPROVAL_REJECTED

        approval = await self._get_approval(user_id, approval_id)
        approval.status = APPROVAL_REJECTED
        await self.session.commit()
        return {"id": str(approval.id), "status": approval.status}
