"""contact_add_zona

Revision ID: a7b8c9d0e1f2
Revises: 652c446806df
Create Date: 2026-08-03 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '652c446806df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('zona', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'zona')
