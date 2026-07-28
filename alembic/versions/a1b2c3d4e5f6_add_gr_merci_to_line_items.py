"""add gr_merci to offer_line_items and order_line_items

Revision ID: a1b2c3d4e5f6
Revises: f2e73c161f58
Create Date: 2026-07-29 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c3a1f2d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('offer_line_items', sa.Column('gr_merci', sa.String(), nullable=True))
    op.add_column('order_line_items', sa.Column('gr_merci', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('offer_line_items', 'gr_merci')
    op.drop_column('order_line_items', 'gr_merci')
