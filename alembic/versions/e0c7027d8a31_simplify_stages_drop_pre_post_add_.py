"""simplify_stages_drop_pre_post_add_scaduta

Revision ID: e0c7027d8a31
Revises: 8d7d888ad392
Create Date: 2026-08-23 14:46:42.222163

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0c7027d8a31'
down_revision: Union[str, None] = '8d7d888ad392'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE opportunities
        SET stage = 'Chiuso Perso', stage_changed_at = NOW()
        WHERE stage IN ('Drop pre-offerta', 'Drop post-offerta')
    """)
    op.execute("""
        UPDATE opportunities
        SET stage = 'Scaduta', stage_changed_at = NOW()
        WHERE stage = 'Offerta Mandata'
        AND (
            data_scadenza < CURRENT_DATE
            OR (
                data_scadenza IS NULL
                AND data_creazione_sap IS NOT NULL
                AND data_creazione_sap < CURRENT_DATE - INTERVAL '30 days'
            )
        )
    """)


def downgrade() -> None:
    pass
