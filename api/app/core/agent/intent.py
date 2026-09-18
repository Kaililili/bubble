"""记忆操作意图检测(规则引擎)

设计依据:对"记住记忆 / 更改记忆"这类标准句式、意图种类少的场景,
规则引擎是性价比最高、最可控的方案(生产 NLU 的通行做法:能用规则就不用 LLM)。
它的作用是给「模型自主调工具」加一层确定性兜底:检测到意图但模型没调工具时,
后端按这里提取的槽位自动补调 remember,保证"说了要记住/换密码"就真的执行。
"""
import re
from dataclasses import dataclass

_SAVE_VERBS = ("记住", "记一下", "记下来", "保存", "存一下", "记着", "记下", "帮我记", "请记")
_UPDATE_VERBS = ("换了", "改成", "更新", "修改", "更换", "改一下", "换成", "重置")
_CRED_WORDS = ("密码", "口令", "token", "密钥", "卡号", "银行卡", "账号", "账户", "passwd", "pwd")
_TODO_WORDS = ("待办", "提醒", "周报", "截止", "作业", "任务", "会议")

# 值提取:优先带分隔符/更新动词/“新密码”的写法,最后兜底“类型词+连续值”
_VALUE_PATTERNS = [
    re.compile(r"(密码|口令|卡号|token|密钥|passwd|pwd)\s*[是:：=为]+\s*([^\s，。；,;！？!?]+)", re.IGNORECASE),
    re.compile(r"(换成|改成|更新为|改为|更换为)\s*([^\s，。；,;！？!?]+)", re.IGNORECASE),
    re.compile(r"新\s*(密码|口令|卡号|token|密钥)\s*[是:：=为]*\s*([^\s，。；,;！？!?]+)", re.IGNORECASE),
    re.compile(r"(密码|口令|卡号|token|密钥|passwd|pwd)\s*([A-Za-z0-9_\-]{4,})", re.IGNORECASE),
]

_KEY_STOPWORDS = tuple(
    sorted(
        _SAVE_VERBS
        + _UPDATE_VERBS
        + ("把", "将", "给我", "帮我", "请帮我", "请", "麻烦", "的", "是", "为", "登录", "账户", "账号", "新", " ", "：", ":", "=", "，", ",", "。", ".", "***"),
        key=len,
        reverse=True,
    )
)


@dataclass
class MemoryIntent:
    action: str  # "remember" / "update"(最终都走 remember 的 upsert)
    type: str  # credential / fact / event / todo
    type_word: str  # "密码" / "卡号" / "周报" ... 可能为空
    key: str  # 归一化归属,如 "bubble"
    value: str | None  # 提取的值,可能为 None(无法提取时兜底不用自动补调)


def detect_memory_intent(text: str) -> MemoryIntent | None:
    """检测用户消息是否含“记住/保存/更新/更换记忆”意图,并提取槽位。"""
    if not text:
        return None

    action = None
    for v in _SAVE_VERBS:
        if v in text:
            action = "remember"
            break
    if action is None:
        for v in _UPDATE_VERBS:
            if v in text:
                action = "update"
                break
    if action is None:
        return None

    lower = text.lower()
    type_word = ""
    mtype = "fact"
    for w in _CRED_WORDS:
        if w in lower:
            type_word = w
            mtype = "credential"
            break
    if not type_word:
        for w in _TODO_WORDS:
            if w in text:
                type_word = w
                mtype = "todo"
                break

    value = None
    for pat in _VALUE_PATTERNS:
        m = pat.search(text)
        if m:
            value = m.group(2).strip() or None
            break

    key = ""
    if mtype == "credential" and type_word:
        idx = lower.find(type_word.lower())
        if idx > 0:
            head = text[:idx]
            for w in _KEY_STOPWORDS:
                head = head.replace(w, "")
            key = head.strip()
    if not key:
        key = "credential" if mtype == "credential" else "memory"

    return MemoryIntent(action=action, type=mtype, type_word=type_word, key=key, value=value)
