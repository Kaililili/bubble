from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class AppException(Exception):
    def __init__(self, code: int = 500, message: str = "服务器内部错误"):
        self.code = code
        self.message = message

    def __str__(self) -> str:
        # 让 AppException 被日志/降级提示打印时能看到原因,而不是空字符串
        return self.message


async def app_exception_handler(request: Request, exc: AppException):
    logger.error(f"AppException: {exc.message}", exc_info=True)
    return JSONResponse(
        status_code=exc.code if exc.code < 500 else 200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕获异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=200,
        content={"code": 500, "message": "服务器内部错误", "data": None},
    )


def register_exception_handlers(app):
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
