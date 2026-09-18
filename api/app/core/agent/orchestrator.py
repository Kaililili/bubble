"""LangGraph Agent 编排:双路径(原生 Function Calling / ReAct)+ 统一事件流

- supports_function_call=True: 原生 bind_tools,模型返回结构化 tool_calls
- supports_function_call=False: ReAct 提示词模拟,系统解析 Action/Action Input

两条路径共用同一工具执行逻辑(结果缓存 / 错误回灌),产出统一事件:
  {"type": "tool_start", "tool", "query"}
  {"type": "tool_result", "tool", "query", "status", "text", "latency_ms"}
  {"type": "token", "text"}
  {"type": "final", "text"}
"""
import asyncio
import json
import logging
import re
import time
from typing import Annotated, Any, Awaitable, Callable, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
MAX_RESULT_PREVIEW = 600

Emit = Callable[[dict], Awaitable[None]]


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    iterations: int
    pending_action: dict | None


def _format_observation(observation: Any) -> str:
    """把工具返回值格式化为可读文本"""
    if isinstance(observation, str):
        return observation
    try:
        return json.dumps(observation, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(observation)


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_PREVIEW:
        return text
    return text[:MAX_RESULT_PREVIEW].rstrip() + "..."


def _handle_approval(formatted: str, tool_name: str) -> tuple[dict | None, str]:
    """确认型工具返回值 → (审批 payload, 给 LLM 的友好文本)。

    敏感工具不直接执行,而是返回 APPROVAL_PREFIX + JSON;这里解析出来交给编排器
    发 tool_approval_required 事件,并换成不带内部标记的提示文本回灌 LLM。
    """
    from .tools.mcp.loader import APPROVAL_PREFIX

    if isinstance(formatted, str) and formatted.startswith(APPROVAL_PREFIX):
        try:
            payload = json.loads(formatted[len(APPROVAL_PREFIX):])
        except json.JSONDecodeError:
            return None, formatted
        friendly = (
            f"该操作需要用户确认后才能执行(工具:{payload.get('tool', tool_name)})。"
            "已生成确认请求,请告知用户等待其在界面上点击「确认执行」,不要重复调用本工具。"
        )
        return payload, friendly
    return None, formatted


def build_function_calling_graph(model, tools: list, emit: Emit):
    """强模型路径:原生 function calling 工具循环"""
    tool_map = {t.name: t for t in tools}
    model_with_tools = model.bind_tools(tools) if tools else model
    # 同一轮内相同工具+参数的结果缓存,避免模型重复调用浪费
    call_cache: dict[str, str] = {}

    async def agent_node(state: AgentState) -> dict:
        full_text = ""
        gathered = None
        async for chunk in model_with_tools.astream(state["messages"]):
            content = chunk.content
            if isinstance(content, str) and content:
                full_text += content
                await emit({"type": "token", "text": content})
            gathered = chunk if gathered is None else gathered + chunk
        return {
            "messages": [gathered],
            "iterations": state["iterations"] + 1,
            "pending_action": None,
        }

    async def tools_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        tool_messages = []
        for tc in getattr(last, "tool_calls", None) or []:
            name = tc.get("name", "")
            args = tc.get("args", {}) or {}
            query = str(args.get("query", "")) if isinstance(args, dict) else ""
            await emit({"type": "tool_start", "tool": name, "query": query})

            try:
                cache_key = f"{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            except (TypeError, ValueError):
                cache_key = f"{name}:{args}"

            status = "success"
            t0 = time.monotonic()
            if cache_key in call_cache:
                formatted = call_cache[cache_key]
                latency_ms = 0
            else:
                tool = tool_map.get(name)
                if tool is None:
                    formatted = f"未知工具:{name}"
                    status = "error"
                else:
                    try:
                        observation = await tool.ainvoke(args)
                        formatted = _format_observation(observation)
                    except Exception as e:
                        logger.exception("工具 %s 执行失败", name)
                        formatted = f"工具执行失败:{e}"
                        status = "error"
                latency_ms = int((time.monotonic() - t0) * 1000)
                approval_payload, friendly = _handle_approval(formatted, name)
                if approval_payload:
                    # 确认型工具:不缓存(每次调用都应生成新审批单)
                    await emit({"type": "tool_approval_required", **approval_payload})
                    formatted = friendly
                elif status == "success":
                    call_cache[cache_key] = formatted

            await emit(
                {
                    "type": "tool_result",
                    "tool": name,
                    "query": query,
                    "status": status,
                    "text": _truncate(formatted),
                    "full_text": formatted,
                    "latency_ms": latency_ms,
                }
            )
            tool_messages.append(ToolMessage(content=formatted, tool_call_id=tc.get("id", name)))
        return {"messages": tool_messages, "pending_action": None}

    def router(state: AgentState) -> str:
        if state["iterations"] >= MAX_TOOL_ITERATIONS:
            return END
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_conditional_edges("agent", router, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    g.set_entry_point("agent")
    return g.compile()


_ACTION_RE = re.compile(r"Action\s*:\s*(.+?)(?:\n|$)")
_ACTION_INPUT_RE = re.compile(r"Action\s*Input\s*:\s*(.+)", re.DOTALL)


def _parse_react(text: str) -> dict | None:
    """从 ReAct 输出中解析 Action / Action Input"""
    action_match = _ACTION_RE.search(text)
    if not action_match:
        return None
    action = action_match.group(1).strip()
    input_match = _ACTION_INPUT_RE.search(text)
    raw = input_match.group(1).strip() if input_match else "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            args = {"query": raw}
    except (ValueError, TypeError):
        args = {"query": raw}
    return {"name": action, "args": args}


def build_react_graph(model, tools: list, emit: Emit):
    """弱模型路径:ReAct 提示词模拟工具循环"""
    tool_map = {t.name: t for t in tools}
    call_cache: dict[str, str] = {}

    async def agent_node(state: AgentState) -> dict:
        full_text = ""
        async for chunk in model.astream(state["messages"]):
            content = chunk.content
            if isinstance(content, str) and content:
                full_text += content
                await emit({"type": "token", "text": content})
        action = _parse_react(full_text)
        return {
            "messages": [AIMessage(content=full_text)],
            "iterations": state["iterations"] + 1,
            "pending_action": action,
        }

    async def tools_node(state: AgentState) -> dict:
        action = state["pending_action"] or {}
        name = action.get("name", "")
        args = action.get("args", {}) or {}
        query = str(args.get("query", "")) if isinstance(args, dict) else ""
        await emit({"type": "tool_start", "tool": name, "query": query})

        try:
            cache_key = f"{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
        except (TypeError, ValueError):
            cache_key = f"{name}:{args}"

        status = "success"
        t0 = time.monotonic()
        if cache_key in call_cache:
            formatted = call_cache[cache_key]
            latency_ms = 0
        else:
            tool = tool_map.get(name)
            if tool is None:
                formatted = f"未知工具:{name}"
                status = "error"
            else:
                try:
                    observation = await tool.ainvoke(args)
                    formatted = _format_observation(observation)
                except Exception as e:
                    logger.exception("工具 %s 执行失败", name)
                    formatted = f"工具执行失败:{e}"
                    status = "error"
            latency_ms = int((time.monotonic() - t0) * 1000)
            approval_payload, friendly = _handle_approval(formatted, name)
            if approval_payload:
                await emit({"type": "tool_approval_required", **approval_payload})
                formatted = friendly
            elif status == "success":
                call_cache[cache_key] = formatted

        await emit(
            {
                "type": "tool_result",
                "tool": name,
                "query": query,
                "status": status,
                "text": _truncate(formatted),
                "full_text": formatted,
                "latency_ms": latency_ms,
            }
        )
        return {"messages": [HumanMessage(content=f"Observation: {formatted}")], "pending_action": None}

    def router(state: AgentState) -> str:
        if state["iterations"] >= MAX_TOOL_ITERATIONS:
            return END
        if state.get("pending_action"):
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_conditional_edges("agent", router, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    g.set_entry_point("agent")
    return g.compile()


async def run_agent(
    model,
    tools: list,
    messages: list,
    supports_function_call: bool,
    emit: Emit,
) -> None:
    """运行 Agent,事件通过 emit 异步推送;结束时统一发出 final 事件"""
    graph = (
        build_function_calling_graph(model, tools, emit)
        if supports_function_call
        else build_react_graph(model, tools, emit)
    )
    state: AgentState = {"messages": messages, "iterations": 0, "pending_action": None}
    try:
        await graph.ainvoke(state)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Agent 编排失败")
        await emit({"type": "error", "message": f"Agent 编排失败:{e}"})
    await emit({"type": "final", "text": ""})
