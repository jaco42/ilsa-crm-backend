"""add_filter_indexes

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_companies_is_visible', 'companies', ['is_visible'])
    op.create_index('ix_companies_agente_ilsa', 'companies', ['agente_ilsa'])
    op.create_index('ix_companies_agente_desco', 'companies', ['agente_desco'])
    op.create_index('ix_order_line_items_categoria', 'order_line_items', ['categoria'])
    op.create_index('ix_offer_line_items_categoria', 'offer_line_items', ['categoria'])


def downgrade() -> None:
    op.drop_index('ix_companies_is_visible', table_name='companies')
    op.drop_index('ix_companies_agente_ilsa', table_name='companies')
    op.drop_index('ix_companies_agente_desco', table_name='companies')
    op.drop_index('ix_order_line_items_categoria', table_name='order_line_items')
    op.drop_index('ix_offer_line_items_categoria', table_name='offer_line_items')
