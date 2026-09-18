"""兴趣归一化:key 归一、分类兜底、相对时间解析、冷却判定(纯规则,可单测)"""
import re

from ....prompts.ontology import ENTITY_TYPES  # noqa: F401
from datetime import date, datetime, timedelta, timezone

CATEGORIES = ("体育", "科技", "影视", "音乐", "美食", "游戏", "学术", "旅行", "其他")
_TYPE_SYNONYMS = {
    "运动": "sport", "体育项目": "sport", "項目": "sport",
    "联赛": "league", "赛事": "league", "比赛": "league", "league": "league",
    "球队": "team", "俱乐部": "team", "队伍": "team",
    "球员": "person", "球星": "person", "人物": "person", "演员": "person", "歌手": "person",
    "组织": "org", "机构": "org", "公司": "org", "学校": "org",
    "作品": "work", "影视作品": "work", "游戏作品": "work", "书籍": "work", "专辑": "work",
    "产品": "product", "商品": "product", "饮品": "product", "设备": "product",
    "地点": "place", "城市": "place", "场所": "place",
    "技术": "tech", "framework": "tech", "框架": "tech", "模型": "tech",
    "事件": "event", "活动": "event",
    "话题": "topic", "领域": "topic", "主题": "topic",
}
COOL_DAYS = 90
COOL_MIN_MENTIONS = 3

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "体育": (
        "nba", "cba", "篮球", "足球", "羽毛球", "乒乓球", "网球", "排球", "跑步", "健身",
        "游泳", "骑行", "滑雪", "球队", "联赛", "世界杯", "欧冠", "勇士", "湖人", "库里",
        "詹姆斯", "梅西", "c罗", "马拉松",
    ),
    "科技": (
        "ai", "人工智能", "大模型", "llm", "agent", "编程", "python", "java", "前端", "后端",
        "算法", "芯片", "机器人", "开源", "linux", "docker", "数据库", "云计算",
    ),
    "影视": ("电影", "电视剧", "美剧", "日剧", "综艺", "动漫", "动画", "纪录片", "影院", "导演", "演员"),
    "音乐": ("音乐", "歌", "乐队", "说唱", "摇滚", "民谣", "古典", "钢琴", "吉他", "演唱会", "播客"),
    "美食": ("美食", "咖啡", "拿铁", "美式", "奶茶", "火锅", "烧烤", "甜点", "烘焙", "料理", "探店", "茶"),
    "游戏": ("游戏", "手游", "端游", "主机", "switch", "steam", "王者", "原神", "lol", "英雄联盟", "dota"),
    "学术": ("论文", "科研", "读研", "考研", "读博", "数学", "物理", "化学", "生物", "经济", "心理学", "历史", "哲学"),
    "旅行": ("旅行", "旅游", "徒步", "露营", "自驾", "登山", "citywalk", "出国", "签证", "景点"),
}

# 归一化时剥离的修饰/噪声词(长词在前,避免"最近"先于"最近在"被替换)
_FILLERS = (
    "我最近在", "最近一直在", "最近在", "最近", "这阵子", "这段时间", "一直以来", "一直在",
    "开始", "迷上", "入坑", "喜欢上", "喜欢", "关注", "在看", "在玩", "在听", "在读", "在学",
    "正在", "研究", "追", "玩", "看", "听", "读", "学", "的", "了", "吧", "呀", "啊", "呢", "我",
)

_END_HINTS = (
    "不再", "不看", "不追", "不玩", "不听", "不读", "不太", "不怎么", "没怎么",
    "少了", "淡了", "弃了", "退坑", "放弃", "脱粉", "结束了", "移除了",
)


def normalize_name(name: str) -> str:
    """展示名:去首尾空白与不可见字符"""
    return re.sub(r"\s+", " ", (name or "").strip())[:128]


def normalize_key(name: str) -> str:
    """归一化唯一键:小写 + 去修饰词 + 去标点空格"""
    text = (name or "").strip().lower()
    text = text.replace("　", " ")
    for filler in _FILLERS:
        text = text.replace(filler, "")
    text = re.sub(r"[\s]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff+#.\-]", "", text)
    return text[:128]


def infer_category(name: str, fallback: str = "其他") -> str:
    """按关键词兜底分类;无法判断归入『其他』"""
    text = (name or "").lower()
    if not text:
        return fallback
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return fallback


def coerce_category(name: str, category: str | None) -> str:
    cat = (category or "").strip()
    return cat if cat in CATEGORIES else infer_category(name)


def coerce_entity_type(name: str, entity_type: str | None, category: str | None = None) -> str:
    """实体类型收敛到受控词表;无法识别时按分类兜底,最后落到 other"""
    value = (entity_type or "").strip().lower()
    if value in ENTITY_TYPES:
        return value
    if value in _TYPE_SYNONYMS:
        return _TYPE_SYNONYMS[value]
    text = (name or "").lower()
    for keyword, mapped in (
        ("联赛", "league"), ("杯", "league"), ("比赛", "league"), ("球队", "team"), ("俱乐部", "team"),
        ("队", "team"), ("球星", "person"), ("教练", "person"), ("影", "work"), ("剧", "work"),
        ("咖啡", "product"), ("拿铁", "product"), ("茶", "product"),
        ("大学", "org"), ("公司", "org"), ("实验室", "org"), ("框架", "tech"), ("模型", "tech"),
    ):
        if keyword in text:
            return mapped
    cat = category or infer_category(name)
    return {"体育": "sport", "影视": "work", "游戏": "work", "美食": "product", "科技": "tech"}.get(
        cat, "other"
    )


def _first_day_of_month(d: date, offset_months: int = 0) -> date:
    month_index = d.month - 1 + offset_months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def parse_time_expr(text: str, base: date | None = None) -> tuple[date | None, date | None]:
    """从原句解析兴趣时间区间,返回 (since, until)。

    支持:2026-07 / 2026年7月 / 上个月 / 去年 / 前年 / 最近 / 这阵子 / 不再看了 等。
    解析不出的部分返回 None。
    """
    if not text:
        return None, None
    base = base or datetime.now(timezone.utc).astimezone().date()
    since: date | None = None
    until: date | None = None

    m = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*月?", text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            since = date(year, month, 1)
    elif "前年" in text:
        since = date(base.year - 2, 1, 1)
    elif "去年" in text:
        since = date(base.year - 1, 1, 1)
    elif "上个月" in text or "上月" in text:
        since = _first_day_of_month(base, -1)
    elif re.search(r"最近\s*(\d{1,2})\s*个?月", text):
        months = int(re.search(r"最近\s*(\d{1,2})\s*个?月", text).group(1))  # type: ignore[union-attr]
        since = _first_day_of_month(base, -min(months, 24))
    elif any(k in text for k in ("最近", "这阵子", "这段时间", "刚开始", "最近才")):
        since = base - timedelta(days=30)

    if any(k in text for k in _END_HINTS):
        until = base

    if since and until and until < since:
        until = None
    return since, until


def compute_status(
    until: date | None,
    last_seen: datetime | None,
    mention_count: int,
    *,
    now: datetime | None = None,
    cool_days: int = COOL_DAYS,
    cool_min_mentions: int = COOL_MIN_MENTIONS,
) -> str:
    """冷却判定:显式结束 → cooled;长期未提及且提及不足 → cooled;否则 active"""
    if until:
        return "cooled"
    if last_seen is None:
        return "active"
    now = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if (now - last_seen) > timedelta(days=cool_days) and mention_count < cool_min_mentions:
        return "cooled"
    return "active"


def merge_aliases(existing: list | None, incoming: list | None) -> list[str]:
    """别名合并去重,保持原有顺序"""
    out: list[str] = []
    for item in list(existing or []) + list(incoming or []):
        value = normalize_name(str(item))
        if value and value not in out:
            out.append(value)
    return out[:20]


# 实体消解用的"通用修饰词":去掉后仍指同一个东西(如 RAG检索项目→rag、V60滤杯→v60)
GENERIC_TOKENS = (
    "检索项目", "研究项目", "学习项目", "应用场景", "相关内容", "相关", "项目", "应用", "平台",
    "系统", "服务", "工具", "课程", "内容", "方面", "领域", "活动", "比赛", "赛事", "产品",
    "作品", "系列", "体验", "使用", "学习", "研究", "检索", "视频", "节目",
    "滤杯", "器具", "设备", "咖啡豆", "手冲壶", "磨豆机", "滤纸",
)


def dedup_key(name: str) -> str:
    """消解键:归一化后再剥掉通用修饰词,用于判断"是不是同一个实体"。

    只做**确定性**判断(不做向量/LLM 推断):
      RAG检索项目 / RAG  →  rag        (同一实体)
      V60 滤杯 / V60     →  v60        (同一实体)
      大模型应用 / 大模型  →  大模型      (同一实体)
      科幻电影 / 电影     →  科幻电影/电影 (不同,科幻电影是子类,不合并)
    """
    base = normalize_key(name)
    if not base:
        return ""
    for token in GENERIC_TOKENS:
        if len(base) > len(token) + 1 and token in base:
            base = base.replace(token, "")
    return base or normalize_key(name)
