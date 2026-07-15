"""company_status_paese_cap_sap_created_at

Revision ID: 4b4edab9f1a4
Revises: 04c9ab28c07a
Create Date: 2026-07-08 17:12:48.636246

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b4edab9f1a4'
down_revision: Union[str, None] = '04c9ab28c07a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


companystatus = sa.Enum('prospect', 'cliente', name='companystatus')


def upgrade() -> None:
    companystatus.create(op.get_bind(), checkfirst=True)
    op.add_column('companies', sa.Column('cap', sa.String(), nullable=True))
    op.add_column('companies', sa.Column('paese', sa.String(), nullable=True))
    op.add_column('companies', sa.Column('status', companystatus, nullable=True))
    op.execute("UPDATE companies SET status = 'cliente'")
    op.alter_column('companies', 'status', nullable=False)
    op.add_column('companies', sa.Column('sap_created_at', sa.Date(), nullable=True))
    op.drop_constraint('companies_partita_iva_key', 'companies', type_='unique')
    op.drop_column('companies', 'is_client')


def downgrade() -> None:
    op.add_column('companies', sa.Column('is_client', sa.BOOLEAN(), autoincrement=False, nullable=False))
    op.create_unique_constraint('companies_partita_iva_key', 'companies', ['partita_iva'])
    op.drop_column('companies', 'sap_created_at')
    op.drop_column('companies', 'status')
    op.drop_column('companies', 'paese')
    op.drop_column('companies', 'cap')
    companystatus.drop(op.get_bind(), checkfirst=True)
