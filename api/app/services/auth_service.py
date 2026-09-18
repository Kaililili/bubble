"""认证业务逻辑"""
from sqlalchemy.ext.asyncio import AsyncSession
from ..repositories.user_repository import UserRepository
from ..core.security import hash_password, verify_password, create_access_token
from ..core.exceptions import AppException


class AuthService:
    """用户注册与登录"""

    def __init__(self, session: AsyncSession):
        self.repo = UserRepository(session)

    async def register(self, username: str, email: str, password: str):
        """注册新用户"""
        # 检查用户名是否已存在
        existing_user = await self.repo.get_by_username(username)
        if existing_user:
            raise AppException(code=400, message="用户名已被注册")

        # 检查邮箱是否已存在
        existing_email = await self.repo.get_by_email(email)
        if existing_email:
            raise AppException(code=400, message="邮箱已被注册")

        # 创建用户
        hashed = hash_password(password)
        user = await self.repo.create(username=username, email=email, hashed_password=hashed)
        return user

    async def login(self, username: str, password: str):
        """登录验证"""
        user = await self.repo.get_by_username(username)
        if not user:
            raise AppException(code=401, message="用户名或密码错误")

        if not verify_password(password, user.hashed_password):
            raise AppException(code=401, message="用户名或密码错误")

        if not user.is_active:
            raise AppException(code=403, message="账号已被禁用")

        token = create_access_token(str(user.id))
        return token, user
