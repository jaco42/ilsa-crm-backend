"""add agent_assignments table

Revision ID: 079c0da3f30f
Revises: f2e73c161f58
Create Date: 2026-08-02 20:31:09.212902

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '079c0da3f30f'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_assignments',
        sa.Column('cliente_sap', sa.String(), nullable=False),
        sa.Column('org_cm',      sa.String(), nullable=False),
        sa.Column('zn',          sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('cliente_sap', 'org_cm'),
    )
    op.create_index('ix_agent_assignments_zn', 'agent_assignments', ['zn'])


def downgrade() -> None:
    op.drop_index('ix_agent_assignments_zn', table_name='agent_assignments')
    op.drop_table('agent_assignments')
