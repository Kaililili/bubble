"""认证 API 路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..schemas.auth_schema import (
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
    TokenResponse,
)
from ..services.auth_service import AuthService
from ..core.dependencies import get_current_user
from ..core.response import success
from ..models.user_model import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(body: UserRegisterRequest, session: AsyncSession = Depends(get_session)):
    """用户注册"""
    svc = AuthService(session)
    user = await svc.register(username=body.username, email=body.email, password=body.password)
    return success(data=UserResponse.model_validate(user).model_dump())


@router.post("/login")
async def login(body: UserLoginRequest, session: AsyncSession = Depends(get_session)):
    """用户登录，返回 JWT token"""
    svc = AuthService(session)
    token, user = await svc.login(username=body.username, password=body.password)
    return success(data=TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    ).model_dump())


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return success(data=UserResponse.model_validate(current_user).model_dump())
