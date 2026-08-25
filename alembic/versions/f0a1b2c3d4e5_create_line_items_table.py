"""create line_items table

Revision ID: f0a1b2c3d4e5
Revises: e0c7027d8a31
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, None] = 'e0c7027d8a31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, 'line_items'):
        op.create_table('line_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_type', sa.String(), nullable=False),
        sa.Column('opportunity_id', sa.UUID(), nullable=True),
        sa.Column('order_id', sa.UUID(), nullable=True),
        sa.Column('codice_sap', sa.String(), nullable=True),
        sa.Column('descrizione_riga', sa.String(), nullable=True),
        sa.Column('quantita', sa.Numeric(), nullable=True),
        sa.Column('unita_misura', sa.String(), nullable=True),
        sa.Column('prezzo_unitario', sa.Numeric(), nullable=True),
        sa.Column('totale_riga', sa.Numeric(), nullable=True),
        sa.Column('categoria', sa.String(), nullable=True),
        sa.Column('prodotto', sa.String(), nullable=True),
        sa.Column('nota', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], ),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
        sa.PrimaryKeyConstraint('id')
        )


def downgrade() -> None:
    op.drop_table('line_items')
