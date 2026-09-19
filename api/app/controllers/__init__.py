from .router import api_router
from . import health_controller
from . import auth_controller
from . import model_config_controller
from . import chat_controller
from . import tool_controller
from . import memory_controller
from . import mcp_controller
from . import interest_controller
from . import emotion_controller
from . import review_controller

# 注册各模块路由
api_router.include_router(health_controller.router)
api_router.include_router(auth_controller.router)
api_router.include_router(model_config_controller.router)
api_router.include_router(chat_controller.router)
api_router.include_router(tool_controller.router)
api_router.include_router(memory_controller.router)
api_router.include_router(mcp_controller.router)
api_router.include_router(interest_controller.router)
api_router.include_router(emotion_controller.router)
api_router.include_router(review_controller.router)
