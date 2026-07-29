"""line_items_add_categoria

Revision ID: a8f3c9b1d2e7
Revises: f2e73c161f58
Create Date: 2026-07-29 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a8f3c9b1d2e7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('offer_line_items', sa.Column('categoria', sa.String(), nullable=True))
    op.add_column('order_line_items', sa.Column('categoria', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('offer_line_items', 'categoria')
    op.drop_column('order_line_items', 'categoria')
