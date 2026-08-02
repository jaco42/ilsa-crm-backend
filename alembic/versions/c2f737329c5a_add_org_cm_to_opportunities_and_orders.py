"""add org_cm to opportunities and orders

Revision ID: c2f737329c5a
Revises: 079c0da3f30f
Create Date: 2026-08-02 21:06:17.182575

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f737329c5a'
down_revision: Union[str, None] = '079c0da3f30f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opportunities', sa.Column('org_cm', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('org_cm', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('opportunities', 'org_cm')
    op.drop_column('orders', 'org_cm')
