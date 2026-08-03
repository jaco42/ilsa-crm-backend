"""company_agente_ilsa_desco

Revision ID: b2c3d4e5f6a7
Revises: f9e8d7c6b5a4
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'f9e8d7c6b5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='companies' AND column_name='agente'
            ) THEN
                ALTER TABLE companies RENAME COLUMN agente TO agente_ilsa;
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE companies ADD COLUMN IF NOT EXISTS agente_desco VARCHAR;
    """)


def downgrade() -> None:
    op.drop_column('companies', 'agente_desco')
    op.execute("ALTER TABLE companies RENAME COLUMN agente_ilsa TO agente")
