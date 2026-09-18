"""LLM 客户端工厂与 Provider 元信息"""

from .client import build_chat_model
from .resolver import get_default_config
from .provider import PROVIDER_DEFAULT_BASE_URL, test_connection

__all__ = ["build_chat_model", "get_default_config", "PROVIDER_DEFAULT_BASE_URL", "test_connection"]
