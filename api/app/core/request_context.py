import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    rid = request_id_var.get()
    if not rid:
        rid = str(uuid.uuid4())[:8]
        request_id_var.set(rid)
    return rid


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求分配唯一 request_id"""

    async def dispatch(self, request: Request, call_next):
        rid = str(uuid.uuid4())[:8]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)
