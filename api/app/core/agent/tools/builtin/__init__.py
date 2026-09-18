"""内置工具"""
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..base import ToolContext, register_tool
from . import memory_tools  # noqa: F401  触发记忆工具注册
from . import interest_tools  # noqa: F401  触发兴趣检索工具注册


class GetCurrentTimeArgs(BaseModel):
    """无参数"""


@register_tool(
    "get_current_time",
    "获取当前日期和时间。当用户询问现在几点、今天的日期、今天是星期几等时间类问题时调用。",
    GetCurrentTimeArgs,
)
async def get_current_time(ctx: ToolContext, **kwargs) -> str:
    now = datetime.now(timezone.utc).astimezone()
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="搜索关键词")


@register_tool(
    "web_search",
    "联网搜索互联网获取最新信息。当用户问题涉及实时信息、新闻、需要确认的事实,或需要搜索才能回答时调用。",
    WebSearchArgs,
    needs_config=True,
)
async def web_search(ctx: ToolContext, query: str) -> str:
    """调用 Tavily 搜索;需要用户在设置中配置 websearch 类型模型(provider=tavily)"""
    import httpx

    from .....repositories.model_config_repository import ModelConfigRepository
    from .....core.security import decrypt_secret

    configs = await ModelConfigRepository(ctx.session).list_by_user(ctx.user_id, model_type="websearch")
    if not configs:
        return "未配置联网搜索服务,无法搜索。请告诉用户先在设置中配置搜索 API Key。"
    config = configs[0]
    api_key = decrypt_secret(config.api_key_encrypted)
    base = (config.base_url or "https://api.tavily.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base}/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"搜索失败:{e}"

    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return "没有搜索到相关结果。"
    lines = []
    for r in results[:5]:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")[:200]
        lines.append(f"- {title}\n  {url}\n  {content}")
    return "\n".join(lines)
