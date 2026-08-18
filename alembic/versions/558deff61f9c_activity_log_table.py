"""activity_log table

Revision ID: 558deff61f9c
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18 16:13:13.080357

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '558deff61f9c'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('activity_log',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_nome', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('company_id', sa.String(), nullable=True),
        sa.Column('company_nome', sa.String(), nullable=True),
        sa.Column('detail', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_activity_log_created_at', 'activity_log', [sa.text('created_at DESC')], unique=False)
    op.create_index('ix_activity_log_user_nome', 'activity_log', ['user_nome'], unique=False)
    op.create_index('ix_activity_log_company_id', 'activity_log', ['company_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_activity_log_company_id', table_name='activity_log')
    op.drop_index('ix_activity_log_user_nome', table_name='activity_log')
    op.drop_index('ix_activity_log_created_at', table_name='activity_log')
    op.drop_table('activity_log')
