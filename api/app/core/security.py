"""密码哈希 + JWT 工具函数 + Fernet 加解密"""
import re
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt
from cryptography.fernet import Fernet
from ..config import settings


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与哈希值匹配"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """创建 JWT access token"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """解码 JWT token，返回 payload；验证失败抛出 JWTError"""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.fernet_key.encode("utf-8"))
    return _fernet


def encrypt_secret(plain: str) -> str:
    """使用 Fernet 加密敏感信息(API Key / 凭证)"""
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted: str) -> str:
    """解密 Fernet 密文"""
    if not encrypted:
        return ""
    return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")


_CRED_TEXT_RE = re.compile(
    r"(密码|口令|password|passwd|pwd|pin|token|密钥|secret|api[_-]?key)"
    r"\s*([是:：=为]+)\s*([^\s，。；,;！？!?]+)",
    re.IGNORECASE,
)

_CARD_TEXT_RE = re.compile(
    r"(卡号|账号|account|银行卡)\s*([是:：=为]+)\s*(\d[\d\s]{4,})",
    re.IGNORECASE,
)


def sanitize_credential_text(text: str) -> str:
    """对文本中的凭证明文做脱敏,防止明文进入对话历史。

    例: "我的密码是123456" -> "我的密码是***"
        "银行卡号是6222021234566666" -> "银行卡号是***6666"
    """
    text = _CRED_TEXT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = _CARD_TEXT_RE.sub(_mask_card_value, text)
    return text


def _mask_card_value(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(3))
    tail = digits[-4:]
    return f"{m.group(1)}{m.group(2)}***{tail}"


_CRED_TYPE_WORDS = (
    "密码", "口令", "卡号", "银行卡", "账号", "账户",
    "token", "密钥", "secret", "password", "passwd", "pin", "pwd",
)

def credential_key(text: str) -> str:
    """提取凭证的归一化归属 key,用于精准匹配"同一个东西"的凭证。

    例: "bubble 密码***" / "bubble密码***" / "bubble账户密码xxx" -> "bubble"
        "Bubble 密码***" / "BUBBLE 密码***" -> "bubble"(统一小写,避免模型大小写差异导致重复)
        "招商银行卡号***6666" -> "招商"
    """
    lower = text.lower()
    cut = len(text)
    for w in _CRED_TYPE_WORDS:
        idx = lower.find(w.lower())
        if idx >= 0:
            cut = min(cut, idx)
    head = text[:cut]
    for w in (
        "记一下", "记下来", "记住", "保存", "帮我", "给我", "请", "麻烦",
        "把", "将", "的", "是", "为", "登录", "应用", "网站", "平台", "官网",
        "换成", "改成", "改为", "更新", "修改", "更换", "重置",
        " ", "：", ":", "=", "，", ",", "。", ".", "***",
    ):
        head = head.replace(w, "")
    return head.strip().lower() or "credential"


def split_credential_display(text: str) -> tuple[str, str]:
    """把凭证脱敏展示 "Bubble 密码***" 拆成 (归属key, 脱敏值),供面板 key-value 展示。"""
    key = credential_key(text)
    rest = text
    idx = text.lower().find(key)
    if idx >= 0:
        rest = text[idx + len(key):].strip()
    return key, rest
