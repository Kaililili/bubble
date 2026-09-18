"""情绪受控词表:离散主情绪 + Russell 情绪环(valence-arousal)参考坐标。

valence(效价):-1 极消极 ~ +1 极积极;arousal(唤醒度):0 极平静 ~ 1 极激动。
参考坐标用于:①提示词锚定;②维度缺失时兜底;③与主情绪做一致性校验(防幻觉)。
"""
EMOTION_VOCAB: dict[str, tuple[str, float, float]] = {
    "喜悦": ("开心、愉快、满足、兴奋的积极情绪", 0.8, 0.7),
    "平静": ("放松、安宁、中性平和的状态", 0.2, 0.2),
    "期待": ("对未来抱有积极的盼望、憧憬", 0.6, 0.6),
    "感动": ("被触动、温暖、感激的情绪", 0.7, 0.5),
    "悲伤": ("难过、失落、沮丧、低落", -0.7, 0.3),
    "愤怒": ("生气、恼火、不满、被冒犯", -0.6, 0.8),
    "恐惧": ("害怕、担忧、不安、惊慌", -0.6, 0.7),
    "焦虑": ("紧张、压力、忐忑、心神不宁", -0.5, 0.7),
    "疲惫": ("劳累、倦怠、精力耗尽", -0.3, 0.2),
    "厌恶": ("反感、嫌恶、排斥", -0.7, 0.5),
    "惊讶": ("意外、震惊、出乎意料(中性偏激动)", 0.1, 0.8),
    "孤独": ("寂寞、被孤立、缺乏陪伴的失落", -0.5, 0.3),
    "中性": ("无明显情绪倾向", 0.0, 0.3),
}

DEFAULT_EMOTION = "中性"

# 负面情绪词规则(用于:①预筛保留;②本轮即时共情提示;③趋势判定)
NEGATIVE_HINTS = (
    "烦", "累", "难过", "难受", "压力", "焦虑", "崩溃", "委屈", "生气", "愤怒", "气死",
    "失眠", "睡不着", "失恋", "分手", "被骂", "挨批", "挂了", "失败", "想哭", "郁闷",
    "emo", "心累", "糟糕", "倒霉", "痛苦", "害怕", "担心", "紧张", "孤独", "无助",
    "绝望", "讨厌", "后悔", "崩溃", "顶不住", "撑不住", "不想", "烦死",
)

# 明确的正向情绪词(同样让预筛放行)
POSITIVE_HINTS = (
    "开心", "高兴", "太棒", "真好", "喜欢", "期待", "激动", "感动", "满足", "幸福",
    "顺利", "成功", "拿到", "赢了", "爽", "舒服", "放松", "惊喜",
)

# 纯指令/查询:没有情绪词时可以跳过分析
COMMAND_HINTS = (
    "帮我查", "查一下", "搜索", "搜一下", "打开", "关闭", "设置", "提醒我", "现在几点",
    "今天几号", "多少钱", "怎么走", "播放", "翻译", "列出", "生成",
)


def is_valid_emotion(emotion: str | None) -> bool:
    return bool(emotion) and emotion.strip() in EMOTION_VOCAB


def normalize_emotion(emotion: str | None) -> str:
    if is_valid_emotion(emotion):
        return str(emotion).strip()
    return DEFAULT_EMOTION


def reference_coords(emotion: str) -> tuple[float, float]:
    info = EMOTION_VOCAB.get(emotion) or EMOTION_VOCAB[DEFAULT_EMOTION]
    return info[1], info[2]


def clamp_valence(value: float) -> float:
    return max(-1.0, min(1.0, value))


def clamp_arousal(value: float) -> float:
    return max(0.0, min(1.0, value))


def clamp_intensity(value: float) -> float:
    return max(0.0, min(1.0, value))


def is_negative(emotion: str) -> bool:
    return reference_coords(emotion)[0] < -0.2


def has_emotion_hint(text: str) -> bool:
    value = text or ""
    return any(h in value for h in NEGATIVE_HINTS) or any(h in value for h in POSITIVE_HINTS)
