"""工具注册中心与内置工具"""
import logging

from .base import REGISTRY, ToolContext, ToolSpec, build_langchain_tool, register_tool
from . import builtin  # noqa: F401  触发内置工具注册
from . import mcp  # noqa: F401  触发 luckin_compare 等 MCP 聚合工具注册
from ....repositories.tool_config_repository import ToolConfigRepository
from ....repositories.model_config_repository import ModelConfigRepository

logger = logging.getLogger(__name__)


async def _tool_configured(session, user_id: str, tool_key: str) -> bool:
    """工具是否已配置(需要配置的工具检查用户配置)"""
    if tool_key == "web_search":
        configs = await ModelConfigRepository(session).list_by_user(user_id, model_type="websearch")
        return bool(configs)
    return True


async def build_enabled_tools(session, user_id: str) -> list:
    """构建当前用户可用(已启用且已配置)的 LangChain 工具列表"""
    rows = await ToolConfigRepository(session).list_by_user(user_id)
    user_set = {r.tool_key: r.enabled for r in rows}
    ctx = ToolContext(session, user_id)
    tools = []
    for key, spec in REGISTRY.items():
        enabled = user_set.get(key, spec.default_enabled)
        if not enabled:
            continue
        if spec.needs_config and not await _tool_configured(session, user_id, key):
            continue
        tools.append(build_langchain_tool(spec, ctx))
    # MCP 工具(动态加载,单 server 失败降级,不影响内置工具)
    try:
        from .mcp.loader import build_mcp_tools as _build_mcp_tools

        tools.extend(await _build_mcp_tools(session, user_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("加载 MCP 工具失败(忽略): %s", e)
    return tools


__all__ = ["REGISTRY", "ToolContext", "ToolSpec", "build_enabled_tools", "register_tool"]
