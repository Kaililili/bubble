from pathlib import Path

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # 应用
    app_name: str = "Bubble"
    env: str = "development"
    debug: bool = True

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "bubble"
    postgres_password: str = "bubble123"
    postgres_db: str = "bubble"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url_sync(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "bubbleneo4j"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # 后台任务模式:inline(进程内 asyncio,本地开发默认)/ celery(进 Redis 队列,进程重启不丢)
    background_mode: str = "inline"
    celery_timezone: str = "Asia/Shanghai"

    # 兴趣抽取批处理:攒够 N 条 或 静默 M 秒触发一次(设为 1 即关闭批处理,逐条抽取)
    interest_batch_size: int = 5
    interest_batch_wait_seconds: int = 60

    # JWT
    # 必须自行配置(见文件末尾校验);生成:python api/gen_keys.py --write
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24小时

    # Fernet (API Key 加密)
    # 必须自行配置;用于加密 API Key / MCP token
    fernet_key: str = ""

    # CORS
    cors_origins: str = '["http://localhost:5173","http://127.0.0.1:5173"]'

    # 情绪助手:强度低于该值不入库(避免中性/指令消息污染曲线)
    emotion_min_intensity: float = 0.2


    @property
    def cors_origin_list(self) -> List[str]:
        import json
        try:
            return json.loads(self.cors_origins)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:5173"]

        # .env 查找顺序:当前工作目录,其次仓库根目录(在 api/ 下执行脚本也能读到根的 .env)
    _ENV_FILES = (
        str(Path.cwd() / ".env"),
        str(Path(__file__).resolve().parents[2] / ".env"),
    )
    model_config = {
        "env_file": _ENV_FILES,
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()

def validate_secrets() -> None:
    """校验密钥(在服务启动时调用,而非 import 时)。

    缺失或格式不对时抛 RuntimeError,并给出可执行的修复命令。
    放在启动阶段执行,这样 init_db / gen_keys 这类不需要密钥的脚本也能正常用。
    """
    problems = []
    if not settings.jwt_secret:
        problems.append("JWT_SECRET(登录 token 签名)未配置")
    if not settings.fernet_key:
        problems.append("FERNET_KEY(API Key / MCP token 加密)未配置")
    elif len(settings.fernet_key) != 44:
        problems.append("FERNET_KEY 格式不正确(Fernet 密钥是 44 字符)")
    if problems:
        raise RuntimeError(
            "[配置缺失] " + ";".join(problems) + "\n"
            "一条命令生成并写入 .env:\n"
            "    python api/gen_keys.py --write\n"
            "或手动生成后填入 .env 的 JWT_SECRET / FERNET_KEY:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
            '    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
            "注意:FERNET_KEY 一旦用于加密就不要更换,否则已存的 API Key / token 将无法解密。"
        )
