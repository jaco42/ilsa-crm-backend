"""contact_rename_provenienza_to_storico_contatti

Revision ID: b7919f9f919d
Revises: 9e39b20e52ff
Create Date: 2026-07-15 23:29:26.548634

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7919f9f919d'
down_revision: Union[str, None] = '9e39b20e52ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('contacts', 'provenienza', new_column_name='storico_contatti')


def downgrade() -> None:
    op.alter_column('contacts', 'storico_contatti', new_column_name='provenienza')
