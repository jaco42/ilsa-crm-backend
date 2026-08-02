"""rename gr_merci->categoria and categoria->prodotto in line items

Revision ID: a1b2c3d4e5f6
Revises: f2e73c161f58
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = '1cbea582eecd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rinomina prima categoria→prodotto, poi gr_merci→categoria (per evitare conflitti)
    op.alter_column('offer_line_items', 'categoria', new_column_name='prodotto')
    op.alter_column('offer_line_items', 'gr_merci',  new_column_name='categoria')
    op.alter_column('order_line_items', 'categoria', new_column_name='prodotto')
    op.alter_column('order_line_items', 'gr_merci',  new_column_name='categoria')


def downgrade() -> None:
    op.alter_column('offer_line_items', 'categoria', new_column_name='gr_merci')
    op.alter_column('offer_line_items', 'prodotto',  new_column_name='categoria')
    op.alter_column('order_line_items', 'categoria', new_column_name='gr_merci')
    op.alter_column('order_line_items', 'prodotto',  new_column_name='categoria')
