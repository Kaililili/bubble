"""Celery 应用:后台任务队列 + 定时调度(beat)。

- 任务丢了不会没:消息进 Redis 队列,worker 挂了重启后继续消费
- 失败自动重试:任务内抛错 -> 指数退避重试(30s / 60s / 120s)
- 定时任务:`beat` 每天跑洞察刷新与社区全量重聚类

启动方式(本地):
    celery -A app.celery_app worker --pool=solo -l info   # Windows 必须 solo
    celery -A app.celery_app beat -l info
Docker 下由 docker-compose 的 worker / beat 服务负责(见 docker-compose.yml)。
"""
from celery import Celery
from celery.schedules import crontab

from .config import settings

celery_app = Celery(
    "bubble",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.celery_timezone,
    enable_utc=True,
    # 任务确认放在执行完成后:worker 崩溃时任务会重新入队(配合任务幂等)
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    broker_connection_retry_on_startup=True,
    # 定时任务
    beat_schedule={
        "insight-refresh-daily": {
            "task": "memory.refresh_all_insights",
            "schedule": crontab(hour=4, minute=30),
        },
        "community-recluster-daily": {
            "task": "interest.recluster_communities",
            "schedule": crontab(hour=4, minute=0),
        },
    },
)

# 显式导入任务模块,保证 worker/beat 启动时任务都已注册
from .tasks import emotion as _emotion_tasks  # noqa: E402,F401
from .tasks import interest as _interest_tasks  # noqa: E402,F401
from .tasks import maintenance as _maintenance_tasks  # noqa: E402,F401
from .tasks import memory as _memory_tasks  # noqa: E402,F401
