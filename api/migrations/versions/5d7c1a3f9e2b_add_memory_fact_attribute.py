"""add memory fact attribute

Revision ID: 5d7c1a3f9e2b
Revises: 8f2c41d7a9b3
Create Date: 2026-09-27 10:00:00.000000

给记忆加"事实属性 + 适用范围"两列,用于显式 remember 普通事实时的候选召回与关系判断。
与 app/db/bootstrap.py 的 ALTER 保持一致(都用 IF NOT EXISTS,重复执行无副作用)。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d7c1a3f9e2b"
down_revision: Union[str, Sequence[str], None] = "8f2c41d7a9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS attribute VARCHAR(50)")
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS scope VARCHAR(100)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS scope")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS attribute")
