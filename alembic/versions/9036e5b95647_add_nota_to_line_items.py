"""add nota to line items

Revision ID: 9036e5b95647
Revises: cda2038ddd76
Create Date: 2026-08-06 10:30:13.758120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9036e5b95647'
down_revision: Union[str, None] = 'cda2038ddd76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('offer_line_items', sa.Column('nota', sa.Text(), nullable=True))
    op.add_column('order_line_items', sa.Column('nota', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('order_line_items', 'nota')
    op.drop_column('offer_line_items', 'nota')
