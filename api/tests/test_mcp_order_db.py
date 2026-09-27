"""阶段三 MCP 下单闭环 DB 自测:预览绑定 / 幂等 / 价格复核 / 超时未知 / 审批原子抢占 / 强制确认。

用 monkeypatch 替代真实 MCP 调用(自动测试绝不下真实订单),真实下单链路另用脚本手工验收。
"""
import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.exceptions import AppException  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.postgres import async_session, engine  # noqa: E402
from app.models.luckin_order_model import (  # noqa: E402
    ORDER_REQUEST_UNKNOWN,
    LuckinOrderPreview,
    LuckinOrderRequest,
)
from app.models.mcp_server_model import MCPServer  # noqa: E402
from app.models.tool_approval_model import (  # noqa: E402
    APPROVAL_PENDING,
    ToolApproval,
)
from app.models.user_model import User  # noqa: E402
from app.services.mcp_service import MCPService  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

_STATE = {"price": 20.0, "create_calls": 0, "create_result": None}


async def _fake_preview(session, user_id, dept_id, product_id, amount=1, specs=None):
    return {
        "sku_code": "sku-1",
        "shop": "东苑5号楼店",
        "product": "生椰拿铁",
        "spec": "大杯",
        "original_price": 32.0,
        "discount_price": _STATE["price"],
        "privilege_money": 12.0,
        "about_time": "12:00",
    }


async def _fake_create(session, user_id, dept_id, product_id, amount, remark, sku_code, specs):
    _STATE["create_calls"] += 1
    return _STATE["create_result"]


async def _fake_execute_mcp_tool(session, server_id, tool_name, args=None):
    return "OK"


async def _run() -> None:
    from app.core.agent.tools.mcp import loader, luckin_compare

    luckin_compare.run_order_preview = _fake_preview
    luckin_compare.run_order_create = _fake_create
    loader.execute_mcp_tool = _fake_execute_mcp_tool

    username = f"codex_mcp_{uuid.uuid4().hex[:6]}"
    async with async_session() as session:
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=hash_password("x"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id
        svc = MCPService(session)
        try:
            # ── 预览:返回 preview_id 并落库 ──
            pv = await svc.preview_order(uid, dept_id=100, product_id=200, amount=1)
            assert pv.get("preview_id"), "预览没有返回 preview_id"
            preview_id = uuid.UUID(pv["preview_id"])
            print("A. preview persisted with preview_id ok")

            # ── 下单成功 + 幂等 ──
            _STATE["create_result"] = {"order_id": "O1", "discount_price": 20.0}
            created = await svc.create_order(
                uid, 100, 200, 1, remark="", request_id="req-1", preview_id=preview_id
            )
            assert created.get("order_id") == "O1" and created.get("status") == "created", created
            assert _STATE["create_calls"] == 1
            again = await svc.create_order(
                uid, 100, 200, 1, request_id="req-1", preview_id=preview_id
            )
            assert again.get("order_id") == "O1", again
            assert _STATE["create_calls"] == 1, "重复请求又执行了一次下单"
            print("B. create + idempotent duplicate ok")

            # ── 预览过期:要求重新预览,不下单 ──
            pv2 = await svc.preview_order(uid, dept_id=100, product_id=200, amount=1)
            await session.execute(
                delete(LuckinOrderPreview).where(
                    LuckinOrderPreview.id == uuid.UUID(pv2["preview_id"])
                )
            )
            # 直接改过期时间
            from datetime import datetime, timedelta, timezone

            expired = LuckinOrderPreview(
                user_id=uid,
                dept_id=100,
                product_id=200,
                amount=1,
                sku_code="sku-1",
                specs=None,
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            session.add(expired)
            await session.commit()
            await session.refresh(expired)
            try:
                await svc.create_order(
                    uid, 100, 200, 1, request_id="req-2", preview_id=expired.id
                )
                raise AssertionError("过期预览没有拦截")
            except AppException as exc:
                assert exc.code == 400 and "过期" in str(exc), exc
            assert _STATE["create_calls"] == 1, "价格变化仍执行了下单"
            print("C1. expired preview blocked, no order created ok")

            # ── 复核价格变化:立即停止下单,要求重新预览 ──
            _STATE["price"] = 20.0
            pv_pre = await svc.preview_order(uid, dept_id=100, product_id=200, amount=1)
            _STATE["price"] = 21.0  # 复核时价格变了
            try:
                await svc.create_order(
                    uid, 100, 200, 1, request_id="req-pre", preview_id=uuid.UUID(pv_pre["preview_id"])
                )
                raise AssertionError("复核价格变化没有拦截")
            except AppException as exc:
                assert exc.code == 409 and "价格" in str(exc), exc
            assert _STATE["create_calls"] == 1, "复核价格变化仍执行了下单"
            print("C1.5. recheck price change blocks order ok")

            # ── 下单结果价与预览价不一致:订单已生成,显式标注 ──
            _STATE["price"] = 20.0
            pv3 = await svc.preview_order(uid, dept_id=100, product_id=200, amount=1)
            _STATE["create_result"] = {"order_id": "O2", "discount_price": 25.0}
            changed = await svc.create_order(
                uid, 100, 200, 1, request_id="req-4", preview_id=uuid.UUID(pv3["preview_id"])
            )
            assert changed.get("order_id") == "O2" and changed.get("price_changed") is True, changed
            assert changed.get("preview_price") == 20.0, changed
            print("C2. price change surfaced in create result ok")

            # ── 超时未知:标记 unknown,不自动重试,重复请求返回 unknown ──
            _STATE["price"] = 20.0
            pv4 = await svc.preview_order(uid, dept_id=100, product_id=200, amount=1)
            _STATE["create_result"] = {"error_type": "timeout", "error": "createOrder 超时(>12s)"}
            try:
                await svc.create_order(
                    uid, 100, 200, 1, request_id="req-3", preview_id=uuid.UUID(pv4["preview_id"])
                )
                raise AssertionError("超时没有转为 unknown")
            except AppException as exc:
                assert exc.code == 409 and "不要重复下单" in str(exc), exc
            row = (
                await session.execute(
                    select(LuckinOrderRequest).where(
                        LuckinOrderRequest.user_id == uid,
                        LuckinOrderRequest.request_id == "req-3",
                    )
                )
            ).scalar_one()
            assert row.status == ORDER_REQUEST_UNKNOWN, row.status
            retry = await svc.create_order(
                uid, 100, 200, 1, request_id="req-3", preview_id=uuid.UUID(pv4["preview_id"])
            )
            assert retry.get("status") == "unknown", retry
            print("D. timeout -> unknown + no auto retry ok")

            # ── 审批:原子抢占 pending→executing,重复确认被拒 ──
            approval = ToolApproval(
                user_id=uid,
                server_id=uuid.uuid4(),
                tool_name="deleteItem",
                display_name="x__deleteItem",
                args={"id": "1"},
                status=APPROVAL_PENDING,
            )
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            done = await svc.approve_tool(uid, approval.id, remember=False)
            assert done["status"] == "executed" and done["result"] == "OK", done
            try:
                await svc.approve_tool(uid, approval.id, remember=False)
                raise AssertionError("重复确认没有被拒绝")
            except AppException as exc:
                assert exc.code in (400, 409), exc.code
            print("E. approval atomic claim ok")

            # ── 强制确认:订单/取消类即使 remember=True 也不能免确认 ──
            mcp = MCPServer(
                user_id=uid,
                name="m",
                transport="streamable_http",
                url="http://127.0.0.1:9/mcp",
                sensitive_tools=["createOrder", "deleteItem"],
            )
            session.add(mcp)
            await session.commit()
            await session.refresh(mcp)
            forced = ToolApproval(
                user_id=uid,
                server_id=mcp.id,
                tool_name="createOrder",
                display_name="m__createOrder",
                args={},
                status=APPROVAL_PENDING,
            )
            await svc._remember_tool_safe(uid, forced)
            await session.refresh(mcp)
            assert "createOrder" in (mcp.sensitive_tools or []), "订单类被错误地免确认了"
            normal = ToolApproval(
                user_id=uid,
                server_id=mcp.id,
                tool_name="deleteItem",
                display_name="m__deleteItem",
                args={},
                status=APPROVAL_PENDING,
            )
            await svc._remember_tool_safe(uid, normal)
            await session.refresh(mcp)
            assert "deleteItem" not in (mcp.sensitive_tools or []), "非订单类没有被正常免确认"
            print("F. forced confirmation for order/pay/cancel ok")
        finally:
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
            print("cleanup: temp user removed")


def test_mcp_order_db() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    test_mcp_order_db()
    print("ALL PASS")
