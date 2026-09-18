"""记忆检索的融合打分(纯函数,可单测)。

分数 = 向量相似度 x 0.7 + 重要度 x 0.15 + 时间新鲜度 x 0.15

权重取舍:非向量信号合计只有 0.3,是**破平局**用的 —— 语义相似度差得明显的记忆,
不会被"更重要/更近"翻盘;只有相似度接近时,重要与新鲜才决定顺序。
"""
from datetime import datetime, timezone

VECTOR_W = 0.7
IMPORTANCE_W = 0.15
RECENCY_W = 0.15
HALF_LIFE_DAYS = 30.0


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def importance_norm(value) -> float:
    try:
        return clamp(float(value or 0) / 10.0)
    except (TypeError, ValueError):
        return 0.0


def recency_score(last_seen: datetime | None, now: datetime | None = None) -> float:
    if last_seen is None:
        return 0.0
    current = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    days = max(0.0, (current - last_seen).total_seconds() / 86400.0)
    return clamp(0.5 ** (days / HALF_LIFE_DAYS))


def fuse_score(
    vec_sim: float | None,
    importance,
    last_seen: datetime | None,
    now: datetime | None = None,
) -> float:
    sim = clamp(float(vec_sim)) if vec_sim is not None else 0.0
    return round(
        VECTOR_W * sim
        + IMPORTANCE_W * importance_norm(importance)
        + RECENCY_W * recency_score(last_seen, now),
        6,
    )
