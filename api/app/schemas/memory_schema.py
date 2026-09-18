"""记忆与用户背景相关 Pydantic Schema"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileUpsertRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=50)
    value: str = Field(..., min_length=1, max_length=500)
    importance: int = Field(0, ge=0, le=10)


class CredentialUpsertRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=50, description="凭证归属,如 bubble / github")
    value: str = Field(..., min_length=1, max_length=500, description="凭证真实值(加密存储,不回显)")


class ProfileResponse(BaseModel):
    id: UUID
    key: str
    value: str
    importance: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryResponse(BaseModel):
    id: UUID
    type: str
    content: str
    importance: int
    created_at: datetime
    updated_at: datetime
    # 凭证专用:归一化归属 key + 脱敏值(便于前端 key-value 展示)
    credential_key: str | None = None
    credential_value: str | None = None

    model_config = {"from_attributes": True}


class RevealResponse(BaseModel):
    content: str
