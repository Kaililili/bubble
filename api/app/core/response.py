from ..config import settings


def success(data=None, message: str = "ok") -> dict:
    return {"code": 200, "message": message, "data": data}


def error(code: int = 500, message: str = "服务器内部错误", data=None) -> dict:
    return {"code": code, "message": message, "data": data}
