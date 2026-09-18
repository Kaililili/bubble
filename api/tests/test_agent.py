"""Agent 编排器自测:function calling 工具循环 / ReAct 解析 / 错误回灌"""
import asyncio
import json
import sys

sys.path.insert(0, "api")

from app.core.agent.orchestrator import _parse_react, run_agent
from langchain_core.messages import AIMessage


class FakeChunk(AIMessage):
    def __init__(self, content="", tool_calls=None):
        super().__init__(content=content, tool_calls=tool_calls or [])

    def __add__(self, other):
        return FakeChunk(
            self.content + other.content,
            other.tool_calls if other.tool_calls else self.tool_calls,
        )


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return f"tool-{self.name}-result:{args.get('query', '')}"


class FakeFCModel:
    def __init__(self, rounds):
        self.rounds = rounds
        self._i = 0

    def bind_tools(self, tools):
        return self

    async def astream(self, messages):
        r = self.rounds[min(self._i, len(self.rounds) - 1)]
        self._i += 1
        yield FakeChunk(r.get("content", ""), r.get("tool_calls", []))


async def main():
    # 1. function calling:第一轮返回 tool_calls,第二轮返回最终文本
    tool = FakeTool("get_current_time")
    events = []

    async def emit(e):
        events.append(e)

    model = FakeFCModel(
        [
            {"tool_calls": [{"id": "1", "name": "get_current_time", "args": {}}]},
            {"content": "现在是 2026-08-24 10:00:00。"},
        ]
    )
    await run_agent(model, [tool], [{"role": "user", "content": "现在几点"}], True, emit)
    print("== function calling events ==")
    for e in events:
        print(json.dumps(e, ensure_ascii=False))
    types = [e["type"] for e in events]
    assert types.count("tool_start") == 1
    assert types.count("tool_result") == 1
    assert types[-1] == "final"
    assert tool.calls == [{}]

    # 2. ReAct 解析器
    assert _parse_react("Thought: 需要查时间\nAction: get_current_time\nAction Input: {}\n") == {
        "name": "get_current_time",
        "args": {},
    }
    assert _parse_react("直接回答") is None
    print("== react parse ok ==")

    # 3. 未知工具:错误回灌,不崩
    events2 = []

    async def emit2(e):
        events2.append(e)

    model2 = FakeFCModel(
        [
            {"tool_calls": [{"id": "2", "name": "no_such_tool", "args": {"query": "x"}}]},
            {"content": "抱歉,我没有这个工具。"},
        ]
    )
    await run_agent(model2, [tool], [{"role": "user", "content": "hi"}], True, emit2)
    errs = [e for e in events2 if e["type"] == "tool_result" and e["status"] == "error"]
    assert errs and "未知工具" in errs[0]["text"]
    print("== unknown tool error ok ==")

    # 4. 工具结果缓存:同轮相同工具+参数只执行一次
    tool3 = FakeTool("web_search")
    events3 = []

    async def emit3(e):
        events3.append(e)

    model3 = FakeFCModel(
        [
            {
                "tool_calls": [
                    {"id": "3", "name": "web_search", "args": {"query": "bubble"}},
                    {"id": "4", "name": "web_search", "args": {"query": "bubble"}},
                ]
            },
            {"content": "查到了。"},
        ]
    )
    await run_agent(model3, [tool3], [{"role": "user", "content": "查一下"}], True, emit3)
    assert len(tool3.calls) == 1, f"缓存失效,执行了 {len(tool3.calls)} 次"
    print("== tool result cache ok ==")

    print("ALL PASS")


asyncio.run(main())
