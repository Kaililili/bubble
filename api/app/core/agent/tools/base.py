"""工具注册中心:统一工具定义,与模型交互协议解耦

工具是"数据"(name/description/args_schema/handler),
Function Calling 与 ReAct 是"引擎",引擎只写一次,新工具只需注册一条数据。
"""
import uuid
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

REGISTRY: dict[str, "ToolSpec"] = {}


class ToolContext:
    """工具执行上下文(会话/用户)"""

    def __init__(self, session: AsyncSession, user_id: uuid.UUID, conversation_id=None):
        self.session = session
        self.user_id = user_id
        # 会话 id:需要"结果异步写回对话"的工具会用到(如长任务受理后回填结果)
        self.conversation_id = conversation_id


class ToolSpec:
    """一条工具定义"""

    def __init__(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel] | None,
        handler: Callable[..., Awaitable[Any]],
        needs_config: bool = False,
        default_enabled: bool = True,
    ):
        self.name = name
        self.description = description
        self.args_schema = args_schema or BaseModel
        self.handler = handler
        self.needs_config = needs_config
        self.default_enabled = default_enabled

    async def execute(self, ctx: ToolContext, **kwargs) -> Any:
        return await self.handler(ctx, **kwargs)


def register_tool(
    name: str,
    description: str = "",
    args_schema: type[BaseModel] | None = None,
    needs_config: bool = False,
    default_enabled: bool = True,
):
    """装饰器注册工具。handler 签名: async def fn(ctx: ToolContext, **kwargs)"""

    def decorator(fn):
        if name in REGISTRY:
            raise ValueError(f"工具 {name} 已注册")
        REGISTRY[name] = ToolSpec(name, description, args_schema, fn, needs_config, default_enabled)
        return fn

    return decorator


def build_langchain_tool(spec: ToolSpec, ctx: ToolContext) -> StructuredTool:
    """把 ToolSpec 转成 LangChain 工具(供 bind_tools / 直接调用)"""

    async def _run(**kwargs):
        return await spec.execute(ctx, **kwargs)

    return StructuredTool.from_function(
        coroutine=_run,
        name=spec.name,
        description=spec.description,
        args_schema=spec.args_schema or None,
    )
