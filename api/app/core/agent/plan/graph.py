"""Plan-Execute 图:plan → execute ↺(replan) → finish。

四拍循环(对应标准 Plan-Execute 模式):

1. **Plan**:一次模型调用产出步骤清单(受控步骤类型 + 依赖 + goal/expect);校验不过就回退默认计划;
2. **Execute**:每次只跑**一个**步骤,执行体是确定性函数(不调模型);
3. **Observe**:按步骤声明的 `expect` 判断这一步算不算做成(没报错但没数据也算没做成);
4. **Re-plan**:数据为空时按规则**插入补救步骤**(扩时间窗),补不动就把缺口记进 degraded——
   全程不额外花模型调用,且有三重上限(重规划 ≤2 次、时间窗 ≤30 天、步骤 ≤8 个)。

降级原则:任何一环失败都不抛异常给上层,而是记进 `degraded`,让报告如实交代缺什么。
"""
from __future__ import annotations

import logging
import time
from contextvars import ContextVar

from langgraph.graph import END, START, StateGraph

from .state import (
    COLLECT_STEPS,
    MAX_REPLANS,
    MAX_WINDOW_DAYS,
    ReviewState,
    default_plan,
    normalize_plan,
)
from .steps import STEP_REGISTRY, ask_model, parse_json

logger = logging.getLogger(__name__)

# 运行时上下文:DB 会话与用户 id 通过 ContextVar 传给节点。
# 不放进 state 是因为 LangGraph 只会传递 TypedDict 里声明的字段,而且 state 保持纯数据更好
# (将来接 checkpointer 做断点续跑时不需要序列化数据库连接)。
_SESSION: ContextVar = ContextVar("review_session")
_USER_ID: ContextVar = ContextVar("review_user_id")


def _runtime():
    return _SESSION.get(), _USER_ID.get()


async def plan_node(state: ReviewState) -> dict:
    """拍一:产出计划(模型优先,失败回退默认计划)"""
    from ....prompts.review import PLAN_PROMPT

    days = int(state.get("window_days") or 7)
    goal = state.get("goal") or f"生成近 {days} 天的个人回顾"
    session, user_id = _runtime()
    answer = await ask_model(session, user_id, PLAN_PROMPT.format(goal=goal, days=days))
    plan = normalize_plan(parse_json(answer) or {}, days)
    source = "llm" if plan else "fallback"
    if not plan:
        plan = default_plan(days)

    # 调用方要求落地时,确保计划里有 persist 步骤(规划器可能没排)
    if state.get("persist") and all(step["type"] != "persist" for step in plan):
        compose_ids = [step["id"] for step in plan if step["type"] == "compose"]
        plan.append(
            {
                "id": f"s{len(plan) + 1}",
                "goal": "把回顾存成一条记忆",
                "type": "persist",
                "args": {},
                "expect": "记忆写入成功",
                "depends_on": compose_ids,
            }
        )

    trace = [
        {
            "node": "plan",
            "source": source,
            "steps": [
                {"id": s["id"], "type": s["type"], "goal": s.get("goal", ""), "expect": s.get("expect", "")}
                for s in plan
            ],
        }
    ]
    return {
        "goal": goal,
        "plan": plan,
        "step_index": 0,
        "results": {},
        "replans": 0,
        "degraded": [],
        "last_status": "ok",
        "trace": trace,
    }


async def execute_node(state: ReviewState) -> dict:
    """拍二 + 拍三:执行当前步骤,并按 expect 记录结果"""
    plan = state["plan"]
    index = int(state.get("step_index") or 0)
    step = plan[index]
    deps = {
        dep: ((state["results"].get(dep) or {}).get("data") or {})
        for dep in step.get("depends_on", [])
    }
    started = time.monotonic()
    session, user_id = _runtime()
    try:
        result = await STEP_REGISTRY[step["type"]](
            session, user_id, step.get("args") or {}, deps
        )
    except Exception as exc:  # noqa: BLE001  单步失败不炸链路
        logger.warning("review step %s failed: %s", step["type"], exc)
        result = {"status": "error", "data": {}, "note": f"{type(exc).__name__}: {exc}"}
    elapsed_ms = int((time.monotonic() - started) * 1000)

    status = result.get("status") or "ok"
    degraded = list(state.get("degraded") or [])
    if status != "ok":
        # 期望没达成就记一笔缺口(包括"没报错但没数据")
        label = step.get("goal") or step["type"]
        degraded.append(f"{label}:{result.get('note') or '没有数据'}(期望:{step.get('expect') or '—'})")

    results = {**state["results"], step["id"]: result}
    trace = list(state.get("trace") or []) + [
        {
            "node": "execute",
            "step": step["id"],
            "type": step["type"],
            "goal": step.get("goal", ""),
            "expect": step.get("expect", ""),
            "status": status,
            "note": result.get("note", ""),
            "ms": elapsed_ms,
        }
    ]
    return {
        "results": results,
        "step_index": index + 1,
        "last_status": status,
        "degraded": degraded,
        "trace": trace,
    }


def route_after_step(state: ReviewState) -> str:
    """拍四的分支:补救 / 继续 / 收尾"""
    if state.get("last_status") in ("empty", "error") and int(state.get("replans") or 0) < MAX_REPLANS:
        return "replan"
    if int(state.get("step_index") or 0) >= len(state.get("plan") or []):
        return "finish"
    return "execute"


async def replan_node(state: ReviewState) -> dict:
    """再计划:能补救就插入补救步骤,补不动就交给 degraded(不花模型调用)"""
    plan = list(state["plan"])
    index = int(state.get("step_index") or 0) - 1
    step = plan[index]
    days = int((step.get("args") or {}).get("days") or 0)
    action = ""
    if step["type"] in COLLECT_STEPS and 0 < days < MAX_WINDOW_DAYS:
        # 扩窗补救:插入一个同类型、更大窗口的步骤,并把它接进下游依赖
        new_id = f"{step['id']}w"
        plan.insert(
            index + 1,
            {
                "id": new_id,
                "goal": f"{step.get('goal') or step['type']}(扩大窗口后重试)",
                "type": step["type"],
                "args": {**(step.get("args") or {}), "days": MAX_WINDOW_DAYS},
                "expect": step.get("expect") or "",
                "depends_on": [],
            },
        )
        for later in plan:
            if later["type"] in COLLECT_STEPS:
                continue
            deps = list(later.get("depends_on") or [])
            if step["id"] in deps and new_id not in deps:
                later["depends_on"] = [*deps, new_id]
        action = f"把 {step['type']} 的时间窗从 {days} 天扩到 {MAX_WINDOW_DAYS} 天重试"
    else:
        action = f"{step.get('goal') or step['type']}:数据仍不足,放弃补救并标注降级"

    trace = list(state.get("trace") or []) + [{"node": "replan", "action": action}]
    return {
        "plan": plan,
        "replans": int(state.get("replans") or 0) + 1,
        "last_status": "ok",  # 交回执行器,避免重复进入 replan
        "trace": trace,
    }


async def finish_node(state: ReviewState) -> dict:
    """收尾:汇总报告;要求落地但计划没排 persist 时补一次"""
    report = ""
    for step in state.get("plan") or []:
        data = (state["results"].get(step["id"]) or {}).get("data") or {}
        if isinstance(data, dict) and data.get("report"):
            report = str(data["report"])
    degraded = list(state.get("degraded") or [])
    if not report:
        report = "## 本次回顾\n\n没有产出内容(各步骤均未返回可汇总的结果)。"
        degraded.append("汇总:没有可用的分析结果")

    persist_ran = any(
        step["type"] == "persist" and (state["results"].get(step["id"]) or {}).get("status") == "ok"
        for step in state.get("plan") or []
    )
    if state.get("persist") and not persist_ran:
        session, user_id = _runtime()
        try:
            await STEP_REGISTRY["persist"](session, user_id, {}, {"report": {"report": report}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("review persist fallback failed: %s", exc)
            degraded.append(f"落地:保存记忆失败({exc})")

    summary = report.strip().split("\n")[0][:120]
    trace = list(state.get("trace") or []) + [{"node": "finish", "report_chars": len(report)}]
    return {"report": report, "summary": summary, "degraded": degraded, "trace": trace}


def build_review_graph():
    """固定五个节点;计划作为数据在 state 里流转(不动态建图)"""
    graph = StateGraph(ReviewState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("replan", replan_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges(
        "execute",
        route_after_step,
        {"execute": "execute", "replan": "replan", "finish": "finish"},
    )
    graph.add_edge("replan", "execute")
    graph.add_edge("finish", END)
    return graph.compile()


_REVIEW_GRAPH = build_review_graph()


async def run_review(session, user_id, *, days: int = 7, persist: bool = False, goal: str | None = None) -> dict:
    """对外入口:对话工具 / REST / 定时任务共用"""
    initial: ReviewState = {
        "user_id": user_id,
        "window_days": days,
        "persist": persist,
        "goal": goal or f"生成近 {days} 天的个人回顾",
    }
    session_token = _SESSION.set(session)
    user_token = _USER_ID.set(user_id)
    try:
        final = await _REVIEW_GRAPH.ainvoke(initial)
    except Exception as exc:  # noqa: BLE001  图整体失败也不抛给上层
        logger.exception("review graph failed")
        return {
            "goal": initial["goal"],
            "days": days,
            "plan": [],
            "steps": [],
            "report": "",
            "summary": "",
            "degraded": [f"执行失败:{exc}"],
            "replans": 0,
            "error": str(exc),
        }
    finally:
        _SESSION.reset(session_token)
        _USER_ID.reset(user_token)
    return {
        "goal": final.get("goal"),
        "days": days,
        "plan": [
            {"id": s["id"], "type": s["type"], "goal": s.get("goal", ""), "expect": s.get("expect", "")}
            for s in final.get("plan") or []
        ],
        "steps": list(final.get("trace") or []),
        "report": final.get("report") or "",
        "summary": final.get("summary") or "",
        "degraded": list(final.get("degraded") or []),
        "replans": int(final.get("replans") or 0),
    }
