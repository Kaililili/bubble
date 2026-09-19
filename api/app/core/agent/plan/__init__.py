"""多步任务编排(Plan-Execute):规划器在运行时产出步骤计划,执行器按依赖逐步执行。

与对话里的 ReAct 循环相对:那条路径是"边想边做、单步决策";这条路径是
"先出计划 → 按计划执行 → 数据不足/失败时重规划 → 成文"。
"""
__all__ = ["run_review"]


def __getattr__(name: str):
    """惰性导出:图实现在 graph.py,避免只导入子模块时也把它拉进来"""
    if name == "run_review":
        from .graph import run_review

        return run_review
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
