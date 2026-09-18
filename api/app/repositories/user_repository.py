"""User 数据访问层"""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.user_model import User


class UserRepository:
    """User CRUD 操作"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, username: str, email: str, hashed_password: str) -> User:
        """创建新用户"""
        user = User(username=username, email=email, hashed_password=hashed_password)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """按 ID 查询用户"""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """按用户名查询"""
        result = await self.session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """按邮箱查询"""
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
