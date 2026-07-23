"""company_rename_provenienza_to_storico_contatti

Revision ID: ae081f5bbedb
Revises: 8e50e68d2580
Create Date: 2026-07-15 19:40:47.704444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae081f5bbedb'
down_revision: Union[str, None] = '8e50e68d2580'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('companies', 'provenienza', new_column_name='storico_contatti')


def downgrade() -> None:
    op.alter_column('companies', 'storico_contatti', new_column_name='provenienza')
