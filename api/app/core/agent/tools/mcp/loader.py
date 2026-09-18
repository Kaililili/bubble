"""MCP 工具加载:基于 langchain-mcp-adapters 把外部 MCP server 工具转成 LangChain 工具。

- build_mcp_tools:对话时调用,读已启用 server → 并行加载 → 白名单过滤 → 工具名清洗+加前缀+去重;
  进程内 TTL 缓存(指纹 = server id + updated_at),避免每轮对话重复握手。
- fetch_tools_meta:测试/同步时调用,连单个 server 拉工具清单(原始 name/description)。

设计要点:
- 单 server 失败降级跳过,不影响其余 server 与内置工具;失败**不写库**(避免 updated_at 变化
  使缓存指纹失效、坏节点拖慢每轮),原因由测试连接接口维护、聚合工具实时检测。
- 默认安全白名单只放行查询类工具(find/query/search/detail/get/list/price/info),
  防止 MCP 里下单/支付等副作用工具被 LLM 误触发;allowed_tools 显式指定则精确匹配。
"""
import asyncio
import json
import logging
import re
import time
import uuid

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.tools.mcp.connection import build_connection
from app.models.mcp_server_model import MCPServer
from app.repositories.mcp_server_repository import MCPServerRepository

logger = logging.getLogger(__name__)

_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_NAME_LEN = 64
_MCP_LOAD_TIMEOUT = 8.0
_MCP_CACHE_TTL = 300.0

# 进程内工具缓存:key=user_id,value=(过期时间戳, server 指纹, 工具列表副本)
_MCP_CACHE: dict[str, tuple[float, str, list[BaseTool]]] = {}

# 默认安全策略:只放行查询类工具
_QUERY_HINTS = ("find", "query", "search", "detail", "get", "list", "price", "info")
# 写操作/资金类语义:命中即视为敏感工具(需用户确认)
_SENSITIVE_HINTS = (
    "create", "update", "delete", "remove", "cancel", "submit", "pay",
    "order", "buy", "refund", "set", "modify", "add", "put", "post",
)

# 确认型工具返回值前缀(内部协议):编排器据此发 tool_approval_required 事件,
# 并把它替换成给 LLM 的友好提示(标记本身不进 LLM 上下文)
APPROVAL_PREFIX = "__APPROVAL_REQUIRED__"


def _sanitize(text: str) -> str:
    """清洗为合法工具名片段:非法字符→_,去首尾下划线;空则回退 'mcp'。"""
    cleaned = _INVALID.sub("_", text or "").strip("_")
    return cleaned or "mcp"


def _is_query_tool(name: str) -> bool:
    lower = (name or "").lower()
    return any(h in lower for h in _QUERY_HINTS)


def _is_sensitive(name: str) -> bool:
    lower = (name or "").lower()
    return any(h in lower for h in _SENSITIVE_HINTS)


def _needs_confirmation(server: MCPServer, tool_name: str) -> bool:
    """兼容入口:是否需要用户确认(等价于分级结果为 sensitive)。"""
    ann = _annotations_map(server).get(tool_name)
    return _classify_tool(server, tool_name, ann) == "sensitive"


def _annotations_map(server: MCPServer) -> dict[str, dict]:
    """从 tools_cache 取 MCP 工具的能力声明(测试连接时同步的 annotations)。"""
    out: dict[str, dict] = {}
    for item in server.tools_cache or []:
        if isinstance(item, dict) and item.get("name"):
            ann = item.get("annotations")
            if isinstance(ann, dict):
                out[item["name"]] = ann
    return out


def _classify_tool(server: MCPServer, tool_name: str, annotations: dict | None) -> str:
    """工具分级(优先级从高到低):

    ① 用户显式配置 sensitive_tools(用户说了算);
    ② MCP annotations:destructiveHint=True 或 readOnlyHint=False → sensitive;
       readOnlyHint=True → safe;
    ③ 无声明 → 启发式(查询词语义为 safe,写操作词/无查询语义为 sensitive,保守)。
    """
    if server.sensitive_tools is not None:
        sensitive = {str(x).lower() for x in server.sensitive_tools}
        return "sensitive" if tool_name.lower() in sensitive else "safe"

    ann = annotations or {}
    if ann.get("destructiveHint") is True:
        return "sensitive"
    if ann.get("readOnlyHint") is True:
        return "safe"
    if ann.get("readOnlyHint") is False:
        return "sensitive"

    if _is_query_tool(tool_name):
        return "safe"
    return "sensitive"


def _default_exposed(tool_name: str, annotations: dict | None) -> bool:
    """默认是否暴露给 AI:只读声明 → 暴露;破坏性/非只读声明 → 不暴露;无声明回退查询词规则。"""
    ann = annotations or {}
    if ann.get("destructiveHint") is True or ann.get("readOnlyHint") is False:
        return False
    if ann.get("readOnlyHint") is True:
        return True
    return _is_query_tool(tool_name)


def _apply_whitelist(
    tools: list[BaseTool], allowed_tools: list | None, annotations: dict[str, dict] | None = None
) -> list[BaseTool]:
    """allowed_tools=None → 默认安全策略(只放行查询类);显式列表 → 精确匹配(空数组=全不放行)。"""
    annotations = annotations or {}
    if allowed_tools is None:
        return [t for t in tools if _default_exposed(t.name, annotations.get(t.name))]
    if not allowed_tools:
        return []
    allow = {str(a).lower() for a in allowed_tools}
    return [t for t in tools if t.name.lower() in allow]


def _servers_fingerprint(servers: list[MCPServer]) -> str:
    parts = [
        f"{s.id}:{s.updated_at.isoformat() if s.updated_at else ''}"
        for s in servers
    ]
    return "|".join(sorted(parts))


async def _load_raw_tools(server: MCPServer) -> list[BaseTool]:
    conn = await build_connection(server)
    return await load_mcp_tools(None, connection=conn)


async def _load_raw_tools_timed(server: MCPServer) -> list[BaseTool]:
    return await asyncio.wait_for(_load_raw_tools(server), timeout=_MCP_LOAD_TIMEOUT)


def _rename(tool: BaseTool, prefix: str, seen: set[str]) -> None:
    """把工具名清洗为合法名({prefix}__{tool}),并在 seen 内去重。"""
    base = f"{prefix}__{_sanitize(tool.name)}"[:_MAX_NAME_LEN]
    name = base
    i = 1
    while name in seen:
        suffix = f"_{i}"
        name = base[: _MAX_NAME_LEN - len(suffix)] + suffix
        i += 1
    seen.add(name)
    tool.name = name


def _make_confirmation_tool(
    tool: BaseTool,
    server: MCPServer,
    original_name: str,
    session: AsyncSession,
    user_id: uuid.UUID,
) -> BaseTool:
    """把敏感工具包装成"确认型工具":调用只生成审批单,不真正执行。"""
    from langchain_core.tools import StructuredTool

    from app.models.tool_approval_model import APPROVAL_PENDING, ToolApproval

    display_name = tool.name

    async def _confirm(**kwargs):
        approval = ToolApproval(
            user_id=user_id,
            server_id=server.id,
            tool_name=original_name,
            display_name=display_name,
            args=kwargs,
            status=APPROVAL_PENDING,
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        payload = {
            "approval_id": str(approval.id),
            "tool": display_name,
            "args": kwargs,
        }
        return APPROVAL_PREFIX + json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=_confirm,
        name=display_name,
        description=(
            f"[需用户确认] {tool.description or ''}\n"
            "调用本工具不会立即执行,而是生成一条确认请求,需用户在界面上点击「确认执行」后才真正生效;"
            "调用后请告知用户等待确认。"
        ),
        args_schema=getattr(tool, "args_schema", None),
    )


async def _collect_renamed(
    items: list[tuple[MCPServer, list[BaseTool]]],
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[BaseTool]:
    """按 server 顺序:白名单过滤 → 清洗工具名 → 敏感工具包成确认型工具。"""
    tools: list[BaseTool] = []
    seen: set[str] = set()
    for server, raw in items:
        prefix = _sanitize(server.name)
        annotations = _annotations_map(server)
        for t in _apply_whitelist(raw, server.allowed_tools, annotations):
            original_name = t.name
            _rename(t, prefix, seen)
            if _classify_tool(server, original_name, annotations.get(original_name)) == "sensitive":
                tools.append(
                    _make_confirmation_tool(t, server, original_name, session, user_id)
                )
                continue
            tools.append(t)
    return tools


async def build_mcp_tools(
    session: AsyncSession, user_id: uuid.UUID
) -> list[BaseTool]:
    """构建该用户所有已启用 MCP server 的工具列表(白名单 + 名称清洗 + 去重)。

    多 server 并行加载;单 server 超时/失败跳过。进程内 TTL 缓存,指纹未变即复用。
    """
    servers = await MCPServerRepository(session).list_by_user(
        user_id, enabled_only=True
    )
    if not servers:
        return []
    # allowed_tools=[] 表示该 server 的底层工具不暴露给 Agent(如瑞幸已由 luckin_compare 聚合),
    # 直接跳过,不建立连接
    servers = [s for s in servers if s.allowed_tools != []]
    if not servers:
        return []

    uid = str(user_id)
    fingerprint = _servers_fingerprint(servers)
    now = time.monotonic()
    cached = _MCP_CACHE.get(uid)
    if cached and cached[0] > now and cached[1] == fingerprint:
        return list(cached[2])

    started = time.monotonic()
    results = await asyncio.gather(
        *[_load_raw_tools_timed(s) for s in servers],
        return_exceptions=True,
    )
    ok_items: list[tuple[MCPServer, list[BaseTool]]] = []
    for server, result in zip(servers, results, strict=True):
        if isinstance(result, BaseException):
            err = (
                f"超时(>{_MCP_LOAD_TIMEOUT:.0f}s)"
                if isinstance(result, TimeoutError)
                else result
            )
            logger.warning("加载 MCP 工具失败(跳过): %s: %s", server.name, err)
            continue
        ok_items.append((server, result))

    tools = await _collect_renamed(ok_items, session, user_id)
    # 成功子集也缓存:坏节点在 TTL 内不重试,避免每轮都等超时
    _MCP_CACHE[uid] = (now + _MCP_CACHE_TTL, fingerprint, list(tools))
    logger.info(
        "MCP 工具加载完成: user=%s servers=%d ok=%d tools=%d elapsed=%.2fs",
        uid,
        len(servers),
        len(ok_items),
        len(tools),
        time.monotonic() - started,
    )
    return tools


async def fetch_tools_meta(server: MCPServer) -> list[dict]:
    """测试连接/同步用:直连 MCP 拉工具清单(原始名 + 参数 schema + annotations 能力声明)。

    annotations 是分级依据(readOnlyHint/destructiveHint 等),必须一起同步下来;
    mcp SDK 的 list_tools 能拿到原始声明,故不再走 adapters 转换。
    """
    from mcp import ClientSession

    conn = await build_connection(server)
    if conn.get("transport") == "sse":
        from mcp.client.sse import sse_client

        cm = sse_client(conn["url"], headers=conn.get("headers"))
    else:
        from mcp.client.streamable_http import streamablehttp_client

        cm = streamablehttp_client(conn["url"], headers=conn.get("headers"))

    out: list[dict] = []
    async with cm as (read, write, _):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools = await mcp_session.list_tools()
            for t in tools.tools:
                ann = getattr(t, "annotations", None)
                annotations = None
                if ann is not None:
                    annotations = {
                        "readOnlyHint": getattr(ann, "readOnlyHint", None),
                        "destructiveHint": getattr(ann, "destructiveHint", None),
                        "idempotentHint": getattr(ann, "idempotentHint", None),
                        "openWorldHint": getattr(ann, "openWorldHint", None),
                        "title": getattr(ann, "title", None),
                    }
                out.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": getattr(t, "inputSchema", None) or {},
                        "annotations": annotations,
                    }
                )
    return out


def _tool_input_schema(tool: BaseTool) -> dict:
    """提取 LangChain 工具的 JSON Schema(兼容 pydantic v1/v2 与 dict 形态)。"""
    try:
        s = tool.get_input_schema()
        if isinstance(s, dict):
            return s
        if hasattr(s, "model_json_schema"):
            return s.model_json_schema()
        if hasattr(s, "schema"):
            return s.schema()
    except Exception:  # noqa: BLE001
        pass
    return {}


def invalidate_mcp_cache(user_id: uuid.UUID | str | None = None) -> None:
    """清除 MCP 工具缓存(增删/改 server 后调用)。None=全部清。"""
    if user_id is None:
        _MCP_CACHE.clear()
    else:
        _MCP_CACHE.pop(str(user_id), None)


async def execute_mcp_tool(
    session: AsyncSession,
    server_id: uuid.UUID,
    tool_name: str,
    args: dict | None = None,
) -> str:
    """审批通过后真正执行 MCP 工具:按 server_id 重连,用原始工具名 + 后端保存的参数。"""
    from mcp import ClientSession

    server = await session.get(MCPServer, server_id)
    if server is None:
        raise ValueError("MCP 配置不存在")
    conn = await build_connection(server)
    if conn.get("transport") == "sse":
        from mcp.client.sse import sse_client

        cm = sse_client(conn["url"], headers=conn.get("headers"))
    else:
        from mcp.client.streamable_http import streamablehttp_client

        cm = streamablehttp_client(conn["url"], headers=conn.get("headers"))
    async with cm as (read, write, _):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            result = await mcp_session.call_tool(tool_name, args or {})
            return "".join(
                str(c.text)
                for c in result.content
                if getattr(c, "text", None) is not None
            )


__all__ = [
    "build_mcp_tools",
    "fetch_tools_meta",
    "invalidate_mcp_cache",
    "_apply_whitelist",
]
