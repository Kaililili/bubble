"""add memory source trace

Revision ID: 8f2c41d7a9b3
Revises: 49c9b8b11f5e
Create Date: 2026-09-26 18:40:00.000000

给记忆加"来源溯源"两列:source(chat/review/manual)与 source_message_id(用户消息 id)。
与 app/db/bootstrap.py 的 ALTER 保持一致(两边都用 IF NOT EXISTS,重复执行无副作用)。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2c41d7a9b3"
down_revision: Union[str, Sequence[str], None] = "49c9b8b11f5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source VARCHAR(16)")
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_message_id UUID")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS source_message_id")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS source")
