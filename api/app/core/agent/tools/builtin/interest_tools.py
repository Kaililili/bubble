"""兴趣检索工具:GraphRAG 多跳"""
from pydantic import BaseModel, Field

from ..base import ToolContext, register_tool


class InterestRecallArgs(BaseModel):
    query: str = Field("", description="要检索的兴趣问题或关键词;问「我都关注过什么」时可留空")
    hops: int = Field(2, ge=1, le=3, description="图扩展跳数,默认 2,最多 3")
    include_cooled: bool = Field(True, description="是否包含已冷却的历史兴趣")


@register_tool(
    "interest_recall",
    "检索用户过去和现在的兴趣(基于兴趣图谱,支持多跳关联)。当用户问自己关注过什么、"
    "以前是否关注过某事物、某两个兴趣有什么关联时调用。返回带时间区间与关联路径的证据;"
    "回答时必须给出时间区间,不要编造未返回的兴趣。同一轮对话中同一问题只需调用一次,不要重复调用。",
    InterestRecallArgs,
)
async def interest_recall(
    ctx: ToolContext, query: str = "", hops: int = 2, include_cooled: bool = True
) -> str:
    from .....core.agent.interest.retriever import recall_text

    return await recall_text(
        ctx.session, ctx.user_id, query, hops=hops, include_cooled=include_cooled
    )


class InterestOverviewArgs(BaseModel):
    query: str = Field("", description="概览问题(可留空),如「我整体关注哪些方向」")


@register_tool(
    "interest_overview",
    "按主题社区总结用户的兴趣全貌(全局检索)。当用户问「我整体关注哪些方向」「我的兴趣主线是什么」"
    "「总结一下我的兴趣画像」这类需要跨多个兴趣概括的问题时调用。返回各兴趣社区的摘要与成员。",
    InterestOverviewArgs,
)
async def interest_overview(ctx: ToolContext, query: str = "") -> str:
    from .....core.agent.interest.community import global_recall

    result = await global_recall(ctx.session, ctx.user_id, query)
    return result["text"]
