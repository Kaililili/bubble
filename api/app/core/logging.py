import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _RequestIdFilter(logging.Filter):
    """把当前请求的 request_id 注入每条日志,便于把一次请求的日志串起来。

    request_id 由 RequestContextMiddleware 用 ContextVar 设置;
    worker / 定时任务里没有请求上下文,记 "-"。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from .request_context import request_id_var

        record.request_id = request_id_var.get() or "-"
        return True


class _SafeStreamHandler(logging.StreamHandler):
    """Windows 兼容 Handler：写入 emoji 失败时自动降级为纯文本"""

    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # 去掉日志消息中的 emoji，用纯文本重新 emit
            msg = record.msg
            if isinstance(msg, str):
                record.msg = msg.encode("ascii", errors="replace").decode("ascii")
            self.stream = open(self.stream.name, "w", encoding="utf-8", errors="replace")
            super().emit(record)


def setup_logging(debug: bool = True):
    level = logging.DEBUG if debug else logging.INFO
    handler = _SafeStreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # 抑制过于啰嗦的第三方日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
