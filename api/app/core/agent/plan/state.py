"""Plan-Execute 的状态定义与默认计划。

关键设计:**计划是数据,不是图结构**。节点固定五个(plan/execute/replan/compose/persist),
步骤列表放在 state 里由执行器逐步消费——这样同一张图能跑不同计划(周报 / 月度回顾 / 单主题深挖)。

每个步骤的字段:
- `id` / `type` / `args` / `depends_on`:执行器需要的机器信息
- `goal`:这一步要完成的子目标(给人审阅计划用)
- `expect`:期望结果(Observe 阶段判断"这步算不算做成"的依据)
"""
from __future__ import annotations

from typing import TypedDict

# 受控步骤类型:规划器只能从这几个里选,executor 靠它做注册表分发
STEP_TYPES = (
    "collect_emotion",
    "collect_interests",
    "collect_memories",
    "analyze",
    "compose",
    "persist",
)

COLLECT_STEPS = ("collect_emotion", "collect_interests", "collect_memories")

# 重规划上限:防止"数据不足 → 换窗口 → 还是不足"无限循环
MAX_REPLANS = 2
# 扩窗上限:超过这个天数就不再扩,直接标注降级
MAX_WINDOW_DAYS = 30


class ReviewState(TypedDict, total=False):
    """图的状态。节点返回的 dict 会被 LangGraph 合并进这里。"""

    user_id: str
    goal: str
    window_days: int
    persist: bool
    # 计划与执行进度
    plan: list[dict]
    step_index: int
    results: dict[str, dict]
    # 重规划与降级
    last_status: str  # ok / empty / error
    replans: int
    degraded: list[str]
    # 产出
    analysis: dict
    report: str
    summary: str
    trace: list[dict]  # 步骤轨迹(前端/日志/验收用)


def default_plan(days: int) -> list[dict]:
    """没有模型时的兜底计划(和有模型时的结构一致,保证执行器只有一条路径)"""
    return [
        {
            "id": "s1",
            "goal": f"拿到近 {days} 天的情绪概况",
            "type": "collect_emotion",
            "args": {"days": days},
            "expect": "至少一条情绪记录",
            "depends_on": [],
        },
        {
            "id": "s2",
            "goal": f"拿到近 {days} 天活跃的兴趣",
            "type": "collect_interests",
            "args": {"days": days},
            "expect": "至少一个活跃兴趣实体",
            "depends_on": [],
        },
        {
            "id": "s3",
            "goal": f"拿到近 {days} 天的新增记忆/事件",
            "type": "collect_memories",
            "args": {"days": days},
            "expect": "至少一条新增记忆",
            "depends_on": [],
        },
        {
            "id": "s4",
            "goal": "把三路数据交叉分析成观察结论",
            "type": "analyze",
            "args": {},
            "expect": "3~5 条基于数据的观察",
            "depends_on": ["s1", "s2", "s3"],
        },
        {
            "id": "s5",
            "goal": "写成一份可读的个人回顾",
            "type": "compose",
            "args": {},
            "expect": "300~500 字的 Markdown 报告",
            "depends_on": ["s4"],
        },
    ]


def normalize_plan(raw: dict, days: int) -> list[dict] | None:
    """校验并规范规划器的输出:类型必须在白名单、依赖必须指向已存在的步骤"""
    steps = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(steps, list) or not steps:
        return None
    out: list[dict] = []
    seen: set[str] = set()
    for index, step in enumerate(steps[:8]):
        if not isinstance(step, dict):
            return None
        step_type = str(step.get("type") or "")
        if step_type not in STEP_TYPES:
            return None
        step_id = str(step.get("id") or f"s{index + 1}")
        deps = [str(d) for d in (step.get("depends_on") or []) if str(d) in seen]
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if step_type in COLLECT_STEPS:
            args = {**args, "days": int(args.get("days") or days)}
        out.append(
            {
                "id": step_id,
                "goal": str(step.get("goal") or "")[:120],
                "type": step_type,
                "args": args,
                "expect": str(step.get("expect") or "")[:120],
                "depends_on": deps,
            }
        )
        seen.add(step_id)
    types = {s["type"] for s in out}
    if "compose" not in types:
        return None
    return out
