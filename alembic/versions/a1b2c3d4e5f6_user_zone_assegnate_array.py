"""user_zone_assegnate_array

Revision ID: a1b2c3d4e5f6
Revises: f9e8d7c6b5a4
Create Date: 2026-08-03 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f9e8d7c6b5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('zone_assegnate', postgresql.ARRAY(sa.String()), nullable=True))
    op.execute("""
        UPDATE users
        SET zone_assegnate = ARRAY[zona_assegnata]
        WHERE zona_assegnata IS NOT NULL AND zona_assegnata != ''
    """)
    op.drop_column('users', 'zona_assegnata')


def downgrade() -> None:
    op.add_column('users', sa.Column('zona_assegnata', sa.String(), nullable=True))
    op.execute("""
        UPDATE users
        SET zona_assegnata = zone_assegnate[1]
        WHERE zone_assegnate IS NOT NULL AND array_length(zone_assegnate, 1) > 0
    """)
    op.drop_column('users', 'zone_assegnate')
