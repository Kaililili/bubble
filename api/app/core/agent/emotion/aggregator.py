"""情绪画像与面板聚合(纯函数,可单测)"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .ontology import DEFAULT_EMOTION, reference_coords


@dataclass
class ProfileAgg:
    dominant_emotion: str
    avg_valence: float
    avg_arousal: float
    sample_count: int
    trend: str  # up / flat / down
    recent_triggers: list[str]
    negative_ratio: float


def aggregate_profile(records: list) -> ProfileAgg:
    """把最近若干条记录聚合成情绪档案(中性也纳入,反映真实基线)"""
    if not records:
        return ProfileAgg(DEFAULT_EMOTION, 0.0, 0.0, 0, "flat", [], 0.0)
    ordered = sorted(records, key=lambda r: r.created_at or datetime.now(timezone.utc))
    n = len(ordered)
    avg_valence = round(sum(r.valence for r in ordered) / n, 4)
    avg_arousal = round(sum(r.arousal for r in ordered) / n, 4)

    counts = Counter(r.emotion_type for r in ordered)
    max_count = max(counts.values())
    candidates = [e for e, c in counts.items() if c == max_count]
    if len(candidates) == 1:
        dominant = candidates[0]
    else:
        intensity_sum: dict[str, float] = defaultdict(float)
        for r in ordered:
            if r.emotion_type in candidates:
                intensity_sum[r.emotion_type] += r.intensity
        dominant = max(intensity_sum, key=lambda k: intensity_sum[k])

    # 趋势:后半段 vs 前半段平均效价
    half = max(1, n // 2)
    older = ordered[:half]
    newer = ordered[-half:]
    older_avg = sum(r.valence for r in older) / len(older)
    newer_avg = sum(r.valence for r in newer) / len(newer)
    delta = newer_avg - older_avg
    trend = "up" if delta > 0.15 else "down" if delta < -0.15 else "flat"

    triggers: list[str] = []
    for r in reversed(ordered):
        if r.trigger and r.trigger not in triggers:
            triggers.append(r.trigger)
        if len(triggers) >= 3:
            break

    negative_ratio = round(
        sum(1 for r in ordered if r.valence < -0.2) / n, 4
    )
    return ProfileAgg(
        dominant_emotion=dominant,
        avg_valence=avg_valence,
        avg_arousal=avg_arousal,
        sample_count=n,
        trend=trend,
        recent_triggers=triggers,
        negative_ratio=negative_ratio,
    )


_TREND_TEXT = {"up": "上行", "flat": "平稳", "down": "下行"}


def format_profile_block(profile: ProfileAgg, *, negative_now: bool = False) -> str:
    """拼成注入 system prompt 的情绪档案块(有记录才返回,≤ 约 200 token)"""
    if profile.sample_count == 0:
        return ""
    lines = [
        "[情绪档案]",
        f"最近 {profile.sample_count} 条记录:主导情绪 {profile.dominant_emotion}"
        f"(平均效价 {profile.avg_valence:+.2f},趋势 {_TREND_TEXT.get(profile.trend, '平稳')},"
        f"消极占比 {profile.negative_ratio:.0%})",
    ]
    if profile.recent_triggers:
        lines.append(f"近期触发:{'、'.join(profile.recent_triggers)}")
    if negative_now:
        lines.append(
            "当前这轮检测到负面信号:请先共情、结合用户背景与相关记忆回应,"
            "不要机械安慰或说教;用户明确要建议时再给具体建议。"
        )
    return "\n".join(lines)


_BUCKET_FMT = {"day": "%Y-%m-%d", "week": None, "month": "%Y-%m"}
_GRANULARITY = ("day", "week", "month")


def _bucket_key(dt: datetime, granularity: str) -> str:
    if granularity == "month":
        return dt.strftime("%Y-%m")
    if granularity == "week":
        monday = dt - timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def bucket_history(records: list, granularity: str = "day") -> list[dict]:
    """按日/周/月分桶,返回 [{bucket, avg_valence, avg_arousal, count, dominant_emotion}]"""
    granularity = granularity if granularity in _GRANULARITY else "day"
    buckets: dict[str, list] = defaultdict(list)
    for r in records:
        if r.created_at is None:
            continue
        buckets[_bucket_key(r.created_at, granularity)].append(r)
    out: list[dict] = []
    for key in sorted(buckets):
        group = buckets[key]
        counts = Counter(r.emotion_type for r in group)
        dominant = counts.most_common(1)[0][0]
        out.append(
            {
                "bucket": key,
                "avg_valence": round(sum(r.valence for r in group) / len(group), 4),
                "avg_arousal": round(sum(r.arousal for r in group) / len(group), 4),
                "count": len(group),
                "dominant_emotion": dominant,
            }
        )
    return out


def build_wordcloud(records: list) -> list[dict]:
    """词云数据:[{word, count, valence}],valence 用于着色"""
    counter: Counter = Counter()
    valence_sum: dict[str, float] = defaultdict(float)
    for r in records:
        for word in (r.keywords or []):
            w = str(word).strip()
            if not w:
                continue
            counter[w] += 1
            valence_sum[w] += r.valence
    return [
        {
            "word": word,
            "count": count,
            "valence": round(valence_sum[word] / count, 3),
        }
        for word, count in counter.most_common(50)
    ]


def emotion_distribution(records: list) -> list[dict]:
    """情绪分布(饼图数据),按参考效价从消极到积极排序"""
    counter = Counter(r.emotion_type for r in records)
    rows = [
        {"emotion_type": e, "count": c, "polarity": reference_coords(e)[0]}
        for e, c in counter.items()
    ]
    rows.sort(key=lambda x: x["polarity"])
    return rows
