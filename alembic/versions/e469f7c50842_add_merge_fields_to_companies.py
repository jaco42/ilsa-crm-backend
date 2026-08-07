"""add merge fields to companies

Revision ID: e469f7c50842
Revises: 9036e5b95647
Create Date: 2026-08-06 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e469f7c50842'
down_revision: Union[str, None] = '9036e5b95647'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('merged_into', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('companies', sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('is_visible', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('companies', 'is_visible')
    op.drop_column('companies', 'merged_at')
    op.drop_column('companies', 'merged_into')
