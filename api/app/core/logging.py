import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


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

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # 抑制过于啰嗦的第三方日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
