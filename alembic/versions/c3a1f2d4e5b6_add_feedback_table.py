"""add feedback table

Revision ID: c3a1f2d4e5b6
Revises: b7919f9f919d
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3a1f2d4e5b6'
down_revision = 'b7919f9f919d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tipo', sa.String(), nullable=False),
        sa.Column('urgenza', sa.String(), nullable=False),
        sa.Column('titolo', sa.String(), nullable=False),
        sa.Column('messaggio', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('feedback')
