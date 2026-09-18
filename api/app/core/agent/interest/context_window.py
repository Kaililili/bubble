"""滑动窗口上下文:抽取时带上最近几条消息,专门用于解析指代。

上下文只帮模型判断 他/她/它/这个/那个 指的是谁,**不能作为证据来源**;
evidence 仍必须来自当前这条消息,由原句接地校验兜底。
"""

CONTEXT_MESSAGES = 4
CONTEXT_LINE_CHARS = 160
NL = chr(10)


def build_context_block(messages, limit=CONTEXT_MESSAGES):
    """把最近几条消息拼成只读上下文块;没有可用消息时返回空串"""
    lines = []
    for item in (messages or [])[-limit:]:
        text = " ".join((item or "").split())
        if text:
            lines.append("历史: " + text[:CONTEXT_LINE_CHARS])
    if not lines:
        return ""
    head = "# 对话上下文(仅供理解指代,不能作为证据)"
    tail = "注意:evidence 必须是当前这句话里的原文片段,上下文只用来判断指代指向谁。"
    return head + NL + NL.join(lines) + NL + tail
