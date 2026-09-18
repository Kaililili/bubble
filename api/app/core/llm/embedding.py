"""Embedding 客户端构建"""
from langchain_openai import OpenAIEmbeddings

from ...models.model_config_model import ModelConfig
from ..security import decrypt_secret


def build_embedding_model(config: ModelConfig) -> OpenAIEmbeddings:
    """根据用户 embedding 配置构建 OpenAI 兼容的 embedding 客户端。

    check_embedding_ctx_length=False 是必须的:langchain 默认用 tiktoken 把文本转成 token
    数组再发请求,OpenAI 之外的兼容服务(硅基流动/DashScope 等)会把 token 当普通文本嵌入,
    导致同文本相似度只有 0.2 左右、检索完全失真。关闭后发送原始文本。
    """
    return OpenAIEmbeddings(
        model=config.model_name,
        api_key=decrypt_secret(config.api_key_encrypted),
        base_url=config.base_url,
        check_embedding_ctx_length=False,
    )
