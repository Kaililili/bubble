"""LLM 客户端构建"""
from langchain_openai import ChatOpenAI
from ...models.model_config_model import ModelConfig
from ..security import decrypt_secret


def build_chat_model(config: ModelConfig, *, streaming: bool = True, temperature: float = 0.7) -> ChatOpenAI:
    """根据用户模型配置构建 ChatOpenAI 客户端(抽取等离线任务可关闭流式、调低温度)"""
    return ChatOpenAI(
        model=config.model_name,
        api_key=decrypt_secret(config.api_key_encrypted),
        base_url=config.base_url,
        streaming=streaming,
        temperature=temperature,
    )
