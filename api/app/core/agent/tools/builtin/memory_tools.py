"""记忆工具:save_profile / remember / recall / forget"""
import re

from pydantic import BaseModel, Field

from ..base import ToolContext, register_tool

_MEMORY_TYPES = ("credential", "fact", "event", "todo")
_SENSITIVE_HINTS = ("密码", "卡号", "账号", "token", "密钥", "身份证", "手机号")
_TODO_HINTS = ("几点", "今天", "明天", "后天", "截止", "待办", "提醒")
_SECRET_HINTS = ("密码", "口令", "token", "密钥", "secret", "password", "passwd", "pin", "pwd")
_CARD_WORDS = ("卡号", "银行卡", "账号", "账户", "account", "身份证", "手机号")


def _infer_type(content: str) -> str:
    text = content.lower()
    if any(hint.lower() in text for hint in _SENSITIVE_HINTS):
        return "credential"
    if any(hint in text for hint in _TODO_HINTS):
        return "todo"
    return "fact"


def _mask_credential(text: str) -> str:
    """凭证脱敏:输出规范化 '<归属> <类型词>***[尾号]'"""
    from .....core.security import credential_key

    lower = text.lower()
    key = credential_key(text)
    for hint in _SECRET_HINTS:
        if hint in lower:
            return f"{key} {hint}***"
    digits = "".join(ch for ch in text if ch.isdigit())
    for w in _CARD_WORDS:
        if w in lower:
            tail = digits[-4:] if len(digits) >= 4 else ""
            return f"{key} {w}***{tail}"
    return f"{key} ***"


class SaveProfileArgs(BaseModel):
    key: str = Field(..., description="背景字段名,如 姓名/过敏/职业/常驻城市")
    value: str = Field(..., description="背景字段值")
    importance: int = Field(0, description="重要性 0-10")


@register_tool(
    "save_profile",
    "把用户的重点基本信息(姓名、过敏、职业、常驻城市、长期偏好等稳定信息)存到用户背景。用户透露这类稳定信息时调用。",
    SaveProfileArgs,
)
async def save_profile(ctx: ToolContext, key: str, value: str, importance: int = 0) -> str:
    from .....repositories.memory_repository import UserProfileRepository

    repo = UserProfileRepository(ctx.session)
    await repo.upsert(ctx.user_id, key, value, importance)
    return f"已记住用户背景:{key}={value}"


class RememberArgs(BaseModel):
    content: str = Field(..., description="要记住的内容原文")
    type: str | None = Field(None, description="类型: credential(敏感)/fact(事实)/event(事件)/todo(待办)")


@register_tool(
    "remember",
    "当用户要求记住/保存/记录/更新/修改/更换信息(如「记住XX」「帮我记一下XX」「记下来」「把密码换了」「更新密码」)时,"
    "必须调用本工具真正保存或更新,不要只在回复中说「已记住/已更新」而不调用工具。"
    "凭证类(密码/卡号/token)会按归属自动覆盖旧值。type 可选:credential(敏感)/fact(事实)/event(事件)/todo(待办)。",
    RememberArgs,
)
async def remember(ctx: ToolContext, content: str, type: str | None = None) -> str:
    from .....core.llm.embedding import build_embedding_model
    from .....core.llm.resolver import get_default_config
    from .....core.security import credential_key, encrypt_secret
    from .....repositories.memory_repository import MemoryRepository

    if not content or not content.strip() or "***" in content:
        return (
            "无法保存:你提供的内容是脱敏占位符(***)或为空,不是有效的真实内容。"
            "请让用户提供真实的密码/信息后再保存,不要假装已保存。"
        )

    mtype = (type or "").lower()
    if mtype not in _MEMORY_TYPES:
        mtype = _infer_type(content)

    content_encrypted = None
    display_content = content
    if mtype == "credential":
        content_encrypted = encrypt_secret(content)
        display_content = _mask_credential(content)

    # 对展示内容(凭证为脱敏描述,不含真实值)生成 embedding,使凭证也能被向量召回
    embedding = None
    try:
        config = await get_default_config(ctx.session, ctx.user_id, "embedding")
        embedder = build_embedding_model(config)
        embedding = await embedder.aembed_query(display_content)
    except Exception:
        embedding = None  # 未配置 embedding 或失败时优雅降级

    repo = MemoryRepository(ctx.session)
    if mtype == "credential":
        # 凭证类 upsert:按归一化应用 key 精准匹配同一凭证,覆盖更新
        key = credential_key(content)
        existing = await repo.find_credential_by_key(ctx.user_id, key)
        if existing:
            existing.content = display_content
            existing.content_encrypted = content_encrypted
            existing.embedding = embedding
            await repo.update(existing)
            return f"已更新凭证:{display_content}"

    memory = await repo.create(
        user_id=ctx.user_id,
        type=mtype,
        content=display_content,
        content_encrypted=content_encrypted,
        embedding=embedding,
    )
    # 事实时效:新事实可能让旧版本失效(凭证类不参与,它们按 key 覆盖)
    if mtype != "credential":
        try:
            from .....core.agent.memory.supersede import apply_supersede

            marked = await apply_supersede(ctx.session, ctx.user_id, memory, embedding)
            if marked:
                return (
                    f"已记住[{mtype}]:{display_content}"
                    + "\n(已把旧记录标记为失效: "
                    + " | ".join(marked[:2])
                    + ")"
                )
        except Exception:  # noqa: BLE001
            pass
    return f"已记住[{mtype}]:{display_content}"


class RecallArgs(BaseModel):
    query: str = Field(..., description="检索词或问题")


@register_tool(
    "recall",
    "检索用户之前提到过的历史记忆。当需要用户过去的信息才能回答问题时调用。",
    RecallArgs,
)
async def recall(ctx: ToolContext, query: str) -> str:
    from .....core.agent.memory.retrieval import search_memories

    top = await search_memories(ctx.session, ctx.user_id, query, limit=6)
    if not top:
        return "没有检索到相关记忆。"
    lines = [f"[{m.type}] {m.content}" for m in top]
    return "\n".join(lines)


class ForgetArgs(BaseModel):
    query: str = Field(..., description="要删除记忆的关键词")


@register_tool(
    "forget",
    "删除一条记忆。当用户要求忘记某条信息,或某条记忆有误时调用。",
    ForgetArgs,
)
async def forget(ctx: ToolContext, query: str) -> str:
    from .....core.llm.embedding import build_embedding_model
    from .....core.llm.resolver import get_default_config
    from .....repositories.memory_repository import MemoryRepository

    repo = MemoryRepository(ctx.session)
    candidates: list = []
    try:
        config = await get_default_config(ctx.session, ctx.user_id, "embedding")
        embedder = build_embedding_model(config)
        vec = await embedder.aembed_query(query)
        candidates.extend(await repo.search_by_vector(ctx.user_id, vec, top_k=3))
    except Exception:
        pass
    candidates.extend(await repo.search_by_keyword(ctx.user_id, query, limit=3))

    seen: set = set()
    unique: list = []
    for c in candidates:
        if c.id in seen:
            continue
        seen.add(c.id)
        unique.append(c)

    if not unique:
        return "没有找到匹配的记忆。"
    target = unique[0]
    await repo.delete(target)
    return f"已删除记忆:[{target.type}] {target.content}"
