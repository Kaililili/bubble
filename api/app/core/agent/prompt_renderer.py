"""Agent 提示词渲染:把工具列表渲染成文本(ReAct 路径用)"""
from langchain_core.tools import BaseTool


def render_tools_prompt(tools: list[BaseTool]) -> str:
    """生成 ReAct 路径的工具说明文本"""
    if not tools:
        return ""
    lines = ["你有以下工具可用:"]
    for t in tools:
        lines.append(f"- {t.name}: {t.description}")
    lines.append(
        "当需要调用工具来回答问题时,请严格按照以下格式输出(不要使用 Markdown 代码块):\n"
        "Thought: <你的思考>\n"
        "Action: <工具名>\n"
        "Action Input: <JSON 格式的参数>\n"
        "工具结果返回后继续思考;如果不需要工具,直接给出最终回答。"
    )
    return "\n".join(lines)
