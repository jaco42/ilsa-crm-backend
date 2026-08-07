"""add original_company_id to contacts and notes

Revision ID: b1c2d3e4f5a6
Revises: e469f7c50842
Create Date: 2026-08-07

"""
from typing import Union
import sqlalchemy as sa
from alembic import op

revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, None] = 'e469f7c50842'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('original_company_id', sa.UUID(), nullable=True))
    op.add_column('notes', sa.Column('original_company_id', sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'original_company_id')
    op.drop_column('notes', 'original_company_id')
