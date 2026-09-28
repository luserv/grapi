"""make run_members a self-contained snapshot

Revision ID: c7e1b4a9d2f3
Revises: a9c03d50635e
Create Date: 2026-09-27 22:40:00.000000

Hace que run_members sea autocontenido: guarda username/full_name/badges en la
misma fila y suelta la FK a instagram_users. Antes esa FK era ON DELETE
CASCADE, así que purgar la caché borraba el historial; además leer el username
a través de la relación devolvía el valor de HOY, no el del análisis.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e1b4a9d2f3'
down_revision: Union[str, Sequence[str], None] = 'a9c03d50635e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar las columnas del snapshot, nullable para poder backfillear.
    op.add_column('run_members', sa.Column('username', sa.String(length=150), nullable=True))
    op.add_column('run_members', sa.Column('full_name', sa.String(length=255), nullable=True))
    op.add_column('run_members', sa.Column('is_verified', sa.Boolean(), nullable=True))
    op.add_column('run_members', sa.Column('is_private', sa.Boolean(), nullable=True))

    # 2. Backfill desde el perfil cacheado. La FK con CASCADE garantiza que cada
    #    run_members tiene su instagram_users, así que el UPDATE no deja huérfanos.
    op.execute("""
        UPDATE run_members m
        SET username     = u.username,
            full_name    = u.full_name,
            is_verified  = COALESCE(u.is_verified, false),
            is_private   = COALESCE(u.is_private, false)
        FROM instagram_users u
        WHERE u.pk = m.user_pk
    """)

    # 3. Si algo quedó sin username (perfil huérfano), se marca para que el
    #    NOT NULL no rompa la migración. Con la FK activa no debería haber, pero
    #    si los hubiera, este UPDATE los delata en vez de abortar en silencio.
    op.execute("""
        UPDATE run_members m
        SET username = '(desconocido:' || m.user_pk || ')'
        WHERE m.username IS NULL
    """)

    op.alter_column('run_members', 'username', nullable=False)
    op.alter_column('run_members', 'is_verified', nullable=False, server_default=sa.false())
    op.alter_column('run_members', 'is_private', nullable=False, server_default=sa.false())

    op.create_index('ix_run_members_username', 'run_members', ['username'])

    # 4. Soltar la FK. El historial deja de depender de la caché: borrar un
    #    perfil de instagram_users ya no arrastra las corridas.
    op.drop_constraint('run_members_user_pk_fkey', 'run_members', type_='foreignkey')


def downgrade() -> None:
    op.create_foreign_key(
        'run_members_user_pk_fkey', 'run_members', 'instagram_users', ['user_pk'], ['pk'],
        ondelete='CASCADE',
    )
    op.drop_index('ix_run_members_username', table_name='run_members')
    op.drop_column('run_members', 'is_private')
    op.drop_column('run_members', 'is_verified')
    op.drop_column('run_members', 'full_name')
    op.drop_column('run_members', 'username')
