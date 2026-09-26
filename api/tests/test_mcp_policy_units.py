"""MCP 工具分级纯函数自测:强制确认 / 白名单 / 只读降级"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.agent.tools.mcp.loader import (  # noqa: E402
    _classify_tool,
    _default_exposed,
    _is_query_tool,
    is_forced_confirm_tool,
)


def _server(sensitive_tools=None):
    return SimpleNamespace(sensitive_tools=sensitive_tools)


def test_forced_confirm() -> None:
    """订单创建/取消/支付/提交类:任何配置都不能绕过强制确认"""
    assert is_forced_confirm_tool("createOrder")
    assert is_forced_confirm_tool("cancelOrder")
    assert is_forced_confirm_tool("pay_order")
    assert not is_forced_confirm_tool("previewOrder")  # 预览是只读,不强制确认
    assert not is_forced_confirm_tool("queryOrderDetailInfo")
    # 即使服务端声明 readOnlyHint=True,也必须是 sensitive
    assert _classify_tool(_server(), "createOrder", {"readOnlyHint": True}) == "sensitive"
    # 即使 sensitive_tools 明确不含它,也必须是 sensitive
    assert _classify_tool(_server(["other"]), "cancelOrder", {"readOnlyHint": True}) == "sensitive"
    print("forced confirm ok")


def test_classify_and_expose() -> None:
    assert _is_query_tool("queryShopList") and _is_query_tool("searchProductForMcp")
    # 服务端 readOnlyHint=True → safe
    assert _classify_tool(_server(), "queryShopList", {"readOnlyHint": True}) == "safe"
    # 服务端 destructiveHint=True → sensitive
    assert _classify_tool(_server(), "deleteItem", {"destructiveHint": True}) == "sensitive"
    # 无声明:查询词 safe,写操作 sensitive
    assert _classify_tool(_server(), "getItems", None) == "safe"
    assert _classify_tool(_server(), "deleteItems", None) == "sensitive"
    # 用户显式 sensitive_tools 优先
    assert _classify_tool(_server(["getItems"]), "getItems", {"readOnlyHint": True}) == "sensitive"
    # 默认暴露:只读/查询词暴露,破坏性不暴露
    assert _default_exposed("queryShopList", {"readOnlyHint": True})
    assert not _default_exposed("createOrder", {"destructiveHint": True})
    print("classify + expose ok")


if __name__ == "__main__":
    test_forced_confirm()
    test_classify_and_expose()
    print("ALL PASS")
