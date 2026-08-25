"""add agente_ilsa_locked and agente_desco_locked to companies

Revision ID: g1h2i3j4k5l6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('companies')]

    if 'agente_ilsa_locked' not in columns:
        op.add_column('companies', sa.Column('agente_ilsa_locked', sa.Boolean(), nullable=False, server_default='false'))

    if 'agente_desco_locked' not in columns:
        op.add_column('companies', sa.Column('agente_desco_locked', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('companies', 'agente_desco_locked')
    op.drop_column('companies', 'agente_ilsa_locked')
