"""add metrics_fetched_at to instagram_users

Revision ID: f4b8c1d3e6a7
Revises: c7e1b4a9d2f3
Create Date: 2026-09-27 22:55:00.000000

Separa la fecha de la identidad de la de los contadores. La identidad
(username/full_name/badges) se relee del listado de following/followers en cada
análisis, así que no necesita cache propia ni vencerse; los contadores sí,
porque refrescarlos cuesta un request por usuario.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b8c1d3e6a7'
down_revision: Union[str, Sequence[str], None] = 'c7e1b4a9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'instagram_users',
        sa.Column('metrics_fetched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_instagram_users_metrics_fetched_at',
        'instagram_users',
        ['metrics_fetched_at'],
    )
    # Los contadores existentes sí se consultaron en su última fetch, así que
    # la fecha honesta para arrancar es esa, no now(). Backfillear con now()
    # haría creer que hay números frescos de hoy cuando en algunos casos son
    # de hace meses.
    op.execute("""
        UPDATE instagram_users
        SET metrics_fetched_at = last_fetched_at
        WHERE metrics_fetched_at IS NULL
    """)


def downgrade() -> None:
    op.drop_index('ix_instagram_users_metrics_fetched_at', table_name='instagram_users')
    op.drop_column('instagram_users', 'metrics_fetched_at')
