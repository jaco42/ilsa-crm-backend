"""company_add_agente

Revision ID: f9e8d7c6b5a4
Revises: c2f737329c5a
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9e8d7c6b5a4'
down_revision: Union[str, None] = 'c2f737329c5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('agente', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'agente')
