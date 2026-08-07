"""add tipo_doc committente_sap nota contribuisce_fatturato

Revision ID: cda2038ddd76
Revises: f3a4b5c6d7e8
Create Date: 2026-08-06 10:10:59.750150

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cda2038ddd76'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opportunities', sa.Column('tipo_doc', sa.String(), nullable=True))
    op.add_column('opportunities', sa.Column('committente_sap', sa.String(), nullable=True))
    op.add_column('opportunities', sa.Column('nota', sa.Text(), nullable=True))
    op.add_column('opportunities', sa.Column('contribuisce_fatturato', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('orders', sa.Column('tipo_doc', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('committente_sap', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('nota', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('contribuisce_fatturato', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    op.drop_column('orders', 'contribuisce_fatturato')
    op.drop_column('orders', 'nota')
    op.drop_column('orders', 'committente_sap')
    op.drop_column('orders', 'tipo_doc')
    op.drop_column('opportunities', 'contribuisce_fatturato')
    op.drop_column('opportunities', 'nota')
    op.drop_column('opportunities', 'committente_sap')
    op.drop_column('opportunities', 'tipo_doc')
