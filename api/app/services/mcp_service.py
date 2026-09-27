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
        from datetime import datetime, timedelta, timezone

        from ..core.agent.tools.mcp.luckin_compare import run_order_preview
        from ..models.luckin_order_model import LuckinOrderPreview

        result = await run_order_preview(
            self.session, user_id, dept_id, product_id, amount, specs
        )
        if "error" in result:
            raise AppException(code=400, message=result["error"])
        # 预览定稿存到服务端:下单只认 preview_id,价格/规格以后端保存的为准(防篡改、防过期)
        preview = LuckinOrderPreview(
            user_id=user_id,
            dept_id=dept_id,
            product_id=product_id,
            amount=amount,
            sku_code=result.get("sku_code") or "",
            specs=specs,
            shop=result.get("shop") or "",
            address=result.get("address"),
            product=result.get("product") or "",
            spec=result.get("spec") or "",
            original_price=result.get("original_price"),
            discount_price=result.get("discount_price"),
            privilege_money=result.get("privilege_money"),
            about_time=result.get("about_time"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        self.session.add(preview)
        await self.session.commit()
        await self.session.refresh(preview)
        result["preview_id"] = str(preview.id)
        result["expires_at"] = preview.expires_at.isoformat()
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
        request_id: str | None = None,
        preview_id: UUID | None = None,
    ) -> dict:
        from datetime import datetime, timezone

        from sqlalchemy import select

        from ..core.agent.tools.mcp.luckin_compare import run_order_create
        from ..models.luckin_order_model import (
            ORDER_REQUEST_CREATED,
            ORDER_REQUEST_FAILED,
            ORDER_REQUEST_UNKNOWN,
            LuckinOrderPreview,
            LuckinOrderRequest,
        )

        row: LuckinOrderRequest | None = None
        # 幂等:同一 request_id 只允许一个执行者;重复请求返回已知结果或"处理中"
        if request_id:
            existing = (
                await self.session.execute(
                    select(LuckinOrderRequest).where(
                        LuckinOrderRequest.user_id == user_id,
                        LuckinOrderRequest.request_id == request_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._order_request_out(existing)
            row = LuckinOrderRequest(
                user_id=user_id,
                request_id=request_id,
                dept_id=dept_id,
                product_id=product_id,
                amount=amount,
                sku_code=sku_code,
            )
            self.session.add(row)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                existing = (
                    await self.session.execute(
                        select(LuckinOrderRequest).where(
                            LuckinOrderRequest.user_id == user_id,
                            LuckinOrderRequest.request_id == request_id,
                        )
                    )
                ).scalar_one_or_none()
                return self._order_request_out(existing)

        async def _fail_request(message: str) -> None:
            """校验/下单失败时,把本次 request_id 标记为 failed(避免留成永久 processing)"""
            if request_id and row is not None:
                row.status = ORDER_REQUEST_FAILED
                row.error = message
                await self.session.commit()

        # 预览绑定:只吃服务端保存的预览参数;前端传的 dept_id/product_id 仅用于一致性校验
        preview: LuckinOrderPreview | None = None
        if preview_id is not None:
            preview = await self.session.get(LuckinOrderPreview, preview_id)
        if preview is None or preview.user_id != user_id:
            await _fail_request("缺少有效的预览记录")
            raise AppException(code=400, message="缺少有效的预览记录,请先预览并确认")
        if (preview.dept_id, preview.product_id) != (dept_id, product_id):
            await _fail_request("下单参数与预览不一致")
            raise AppException(code=400, message="下单参数与预览不一致,请重新预览")
        now = datetime.now(timezone.utc)
        if preview.expires_at is not None and preview.expires_at < now:
            await _fail_request("预览已过期")
            raise AppException(code=400, message="预览已过期,请重新预览")

        # 价格/规格复核:尽量再查一次。确认不一致 → 立即停止下单(要求重新预览);
        # 复核本身读不到(超时/服务抖动) → 放行,由预览 TTL 与下单结果 price_changed 兜底。
        from ..core.agent.tools.mcp.luckin_compare import run_order_preview

        fresh = await run_order_preview(
            self.session,
            user_id,
            preview.dept_id,
            preview.product_id,
            preview.amount,
            preview.specs,
        )
        if "error" not in fresh:
            price_changed = fresh.get("discount_price") != preview.discount_price
            sku_changed = fresh.get("sku_code") != preview.sku_code
            if price_changed or sku_changed:
                await _fail_request("价格或规格已变化")
                raise AppException(code=409, message="价格或规格已发生变化,请重新预览确认")

        # 用服务端保存的 sku/specs 下单(前端传的价格/参数一律不用)
        result = await run_order_create(
            self.session,
            user_id,
            preview.dept_id,
            preview.product_id,
            preview.amount,
            remark,
            preview.sku_code,
            preview.specs,
        )
        if "error" in result:
            timeout = result.get("error_type") == "timeout"
            if request_id and row is not None:
                row.status = ORDER_REQUEST_UNKNOWN if timeout else ORDER_REQUEST_FAILED
                row.error = result["error"]
                await self.session.commit()
            if timeout:
                # 结果未知:绝不自动重试下单,提示用户查询订单状态
                raise AppException(
                    code=409,
                    message="下单请求已发出,但结果未知(服务超时)。请查询订单状态确认后再操作,不要重复下单。",
                )
            raise AppException(code=400, message=result["error"])
        result["status"] = "created"
        # 下单实际价与预览价不一致时,显式标注,让前端/用户看到变化(订单已生成,可取消)
        if (
            result.get("discount_price") is not None
            and preview.discount_price is not None
            and float(result.get("discount_price")) != float(preview.discount_price)
        ):
            result["price_changed"] = True
            result["preview_price"] = preview.discount_price
        if request_id and row is not None:
            row.status = ORDER_REQUEST_CREATED
            row.order_id = result.get("order_id")
            row.result = result
            await self.session.commit()
        return result

    def _order_request_out(self, row) -> dict:
        """把幂等请求行转成对外结果(重复请求返回已知结果或处理中)"""
        from ..models.luckin_order_model import (
            ORDER_REQUEST_CREATED,
            ORDER_REQUEST_FAILED,
            ORDER_REQUEST_PENDING,
            ORDER_REQUEST_UNKNOWN,
        )

        out: dict = {"request_id": row.request_id, "status": row.status}
        if row.status == ORDER_REQUEST_CREATED and row.result:
            out.update({k: v for k, v in row.result.items() if k not in ("status",)})
            out["status"] = "created"
        elif row.status == ORDER_REQUEST_UNKNOWN:
            out["status"] = "unknown"
            out["message"] = "上一次下单结果未知,请查询订单状态确认,不要重复下单"
        elif row.status == ORDER_REQUEST_FAILED:
            out["status"] = "failed"
            out["error"] = row.error
        elif row.status == ORDER_REQUEST_PENDING:
            out["status"] = "processing"
            out["message"] = "该请求正在处理中"
        if row.order_id:
            out["order_id"] = row.order_id
        return out

    async def cancel_order(self, user_id: UUID, order_id: str) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_cancel

        result = await run_order_cancel(self.session, user_id, order_id)
        if "error" in result:
            if result.get("error_type") == "timeout":
                return {"status": "unknown", "message": result["error"]}
            raise AppException(code=400, message=result["error"])
        return {**result, "status": "cancelled"}

    async def query_order(self, user_id: UUID, order_id: str) -> dict:
        from ..core.agent.tools.mcp.luckin_compare import run_order_query

        result = await run_order_query(self.session, user_id, order_id)
        if "error" in result:
            if result.get("error_type") == "timeout":
                return {"status": "unknown", "message": result["error"]}
            raise AppException(code=400, message=result["error"])
        return {**result, "status": "ok"}

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

        from sqlalchemy import text

        from ..core.agent.tools.mcp.loader import execute_mcp_tool
        from ..models.tool_approval_model import (
            APPROVAL_EXECUTED,
            APPROVAL_EXECUTING,
            APPROVAL_EXPIRED,
            APPROVAL_FAILED,
            APPROVAL_PENDING,
            ToolApproval,
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
        # 原子抢占 pending→executing:并发确认只允许一个执行者
        claimed = await self.session.execute(
            text(
                "UPDATE tool_approvals SET status = :st, updated_at = now() "
                "WHERE id = :id AND user_id = :uid AND status = :p RETURNING id"
            ),
            {"st": APPROVAL_EXECUTING, "id": approval_id, "uid": user_id, "p": APPROVAL_PENDING},
        )
        if claimed.first() is None:
            current = await self.session.get(ToolApproval, approval_id)
            state = current.status if current is not None else "不存在"
            raise AppException(code=409, message=f"该请求已被处理({state})")
        await self.session.commit()
        await self.session.refresh(approval)
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
            is_forced_confirm_tool,
        )
        from ..models.mcp_server_model import MCPServer

        # 订单/支付/取消类操作:即使勾选"记住",也始终要求本次确认
        if is_forced_confirm_tool(approval.tool_name):
            return
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
