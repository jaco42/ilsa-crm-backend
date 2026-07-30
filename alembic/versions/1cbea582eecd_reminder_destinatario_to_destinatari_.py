"""reminder_destinatario_to_destinatari_array

Revision ID: 1cbea582eecd
Revises: c2d3e4f5a6b7
Create Date: 2026-07-30 15:55:07.725538

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '1cbea582eecd'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aggiunge la nuova colonna array (nullable temporaneamente per la migrazione dati)
    op.add_column('email_reminders', sa.Column('destinatari', postgresql.ARRAY(sa.String()), nullable=True))
    # Migra i dati esistenti: wrap destinatario singolo in array
    op.execute("UPDATE email_reminders SET destinatari = ARRAY[destinatario]")
    # Rende NOT NULL dopo la migrazione
    op.alter_column('email_reminders', 'destinatari', nullable=False)
    # Rimuove la vecchia colonna
    op.drop_column('email_reminders', 'destinatario')


def downgrade() -> None:
    op.add_column('email_reminders', sa.Column('destinatario', sa.VARCHAR(), nullable=True))
    op.execute("UPDATE email_reminders SET destinatario = destinatari[1]")
    op.alter_column('email_reminders', 'destinatario', nullable=False)
    op.drop_column('email_reminders', 'destinatari')
