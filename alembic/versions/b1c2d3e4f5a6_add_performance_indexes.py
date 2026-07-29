"""add_performance_indexes

Revision ID: b1c2d3e4f5a6
Revises: a8f3c9b1d2e7
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a8f3c9b1d2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_order_line_items_order_id', 'order_line_items', ['order_id'])
    op.create_index('ix_order_line_items_gr_merci', 'order_line_items', ['gr_merci'])
    op.create_index('ix_offer_line_items_opportunity_id', 'offer_line_items', ['opportunity_id'])
    op.create_index('ix_offer_line_items_gr_merci', 'offer_line_items', ['gr_merci'])
    op.create_index('ix_opportunities_company_id', 'opportunities', ['company_id'])
    op.create_index('ix_opportunities_data_creazione_sap', 'opportunities', ['data_creazione_sap'])
    op.create_index('ix_opportunities_stage', 'opportunities', ['stage'])
    op.create_index('ix_orders_company_id', 'orders', ['company_id'])
    op.create_index('ix_orders_data_ordine', 'orders', ['data_ordine'])
    op.create_index('ix_companies_sap_customer_id', 'companies', ['sap_customer_id'])
    op.create_index('ix_companies_status', 'companies', ['status'])


def downgrade() -> None:
    op.drop_index('ix_order_line_items_order_id', table_name='order_line_items')
    op.drop_index('ix_order_line_items_gr_merci', table_name='order_line_items')
    op.drop_index('ix_offer_line_items_opportunity_id', table_name='offer_line_items')
    op.drop_index('ix_offer_line_items_gr_merci', table_name='offer_line_items')
    op.drop_index('ix_opportunities_company_id', table_name='opportunities')
    op.drop_index('ix_opportunities_data_creazione_sap', table_name='opportunities')
    op.drop_index('ix_opportunities_stage', table_name='opportunities')
    op.drop_index('ix_orders_company_id', table_name='orders')
    op.drop_index('ix_orders_data_ordine', table_name='orders')
    op.drop_index('ix_companies_sap_customer_id', table_name='companies')
    op.drop_index('ix_companies_status', table_name='companies')
