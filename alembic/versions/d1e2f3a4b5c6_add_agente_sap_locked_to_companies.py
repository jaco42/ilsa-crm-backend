"""add agente_sap_locked to companies

Revision ID: d1e2f3a4b5c6
Revises: c9d8e7f6a5b4
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'd1e2f3a4b5c6'
down_revision = 'c9d8e7f6a5b4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('companies', sa.Column('agente_sap_locked', sa.Boolean(), nullable=False, server_default='false'))
    # Backfill: lock companies where SAP has provided agent data (i.e., sap_customer_id exists in agent_assignments)
    op.execute("""
        UPDATE companies
        SET agente_sap_locked = TRUE
        WHERE sap_customer_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM agent_assignments
            WHERE agent_assignments.cliente_sap = companies.sap_customer_id
          )
    """)


def downgrade():
    op.drop_column('companies', 'agente_sap_locked')
