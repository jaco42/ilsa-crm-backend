"""drop_prodotti_table_and_canale_acquisizione

Revision ID: 8d7d888ad392
Revises: 558deff61f9c
Create Date: 2026-08-23 13:36:49.577522

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d7d888ad392'
down_revision: Union[str, None] = '558deff61f9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('prodotti')
    op.drop_column('opportunities', 'canale_acquisizione')


def downgrade() -> None:
    op.add_column('opportunities', sa.Column('canale_acquisizione', sa.String(), nullable=True))
    op.create_table(
        'prodotti',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('codice_sap', sa.String(), nullable=True, unique=True),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('categoria', sa.String(), nullable=True),
        sa.Column('attivo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
