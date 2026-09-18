"""会话上下文窗口与滚动摘要的纯逻辑(可单测)。"""

# 保留最近 N 条原文进上下文
RECENT_WINDOW = 40
# 溢出消息累计超过这个数量才值得压一次摘要(避免每轮都调模型)
SUMMARY_TRIGGER = 16
# 摘要长度上限(字符),防止摘要本身膨胀
SUMMARY_MAX_CHARS = 800


def split_window(messages: list, window: int = RECENT_WINDOW) -> tuple[list, list]:
    """把时间正序的消息切成 (溢出部分, 最近窗口);窗口大于总数时溢出为空"""
    if window <= 0:
        return list(messages), []
    if len(messages) <= window:
        return [], list(messages)
    return list(messages[:-window]), list(messages[-window:])


def pending_overflow(messages: list, summarized_until_id, window: int = RECENT_WINDOW) -> list:
    """尚未被摘要覆盖的溢出消息(按时间正序);已摘要部分跳过"""
    overflow, _recent = split_window(messages, window)
    if not overflow:
        return []
    if summarized_until_id is None:
        return overflow
    for index, message in enumerate(overflow):
        if getattr(message, "id", None) == summarized_until_id:
            return overflow[index + 1 :]
    # 摘要游标不在溢出区(数据被删/窗口变化)时,全量重来一次保证不丢信息
    return overflow


def should_summarize(pending: list, trigger: int = SUMMARY_TRIGGER) -> bool:
    return len(pending) >= trigger


def render_messages(messages: list, char_budget: int = 6000) -> str:
    """把消息渲染成摘要输入文本;超出字符预算时保留最近的(旧的先丢)"""
    lines: list[str] = []
    for message in reversed(messages):
        content = (getattr(message, "content", "") or "").strip().replace("\n", " ")
        if not content:
            continue
        role = "用户" if getattr(message, "role", "") == "user" else "助手"
        lines.append(f"{role}: {content[:400]}")
    lines.reverse()
    text = "\n".join(lines)
    while len(text) > char_budget and "\n" in text:
        text = text.split("\n", 1)[1]
    return text


def format_summary_block(summary: str, older_count: int) -> str:
    """注入 system prompt 的摘要块;无摘要返回空串"""
    text = (summary or "").strip()
    if not text:
        return ""
    return (
        f"[本会话早期对话摘要](已压缩 {older_count} 条较早消息,"
        "细节可继续对话或让用户重申):\n" + text[:SUMMARY_MAX_CHARS]
    )
