"""radar_categorie_l1_l2_zona

Revision ID: f3a4b5c6d7e8
Revises: a7b8c9d0e1f2
Create Date: 2026-08-03 19:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('radar_prodotti', sa.Column('categoria_l1', sa.String(), nullable=True))
    op.add_column('radar_prodotti', sa.Column('categoria_l2', sa.String(), nullable=True))
    op.add_column('radar_segnalazioni', sa.Column('zona', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('radar_prodotti', 'categoria_l1')
    op.drop_column('radar_prodotti', 'categoria_l2')
    op.drop_column('radar_segnalazioni', 'zona')
