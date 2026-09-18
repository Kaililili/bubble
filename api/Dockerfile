# 后端镜像:uv 管理依赖 + FastAPI(uvicorn)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:python3.13-bookworm-slim
FROM ${UV_IMAGE}

WORKDIR /app

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# 先装依赖(利用层缓存)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY api/ .
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
