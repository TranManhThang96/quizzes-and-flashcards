"""sources and generation jobs

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03 23:12:15.571514

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('sources',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind in ('text', 'pdf', 'url')", name=op.f('ck_sources_kind')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_sources_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sources'))
    )
    op.create_table('generation_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status in ('queued', 'running', 'succeeded', 'failed')", name=op.f('ck_generation_jobs_status')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_generation_jobs_created_by_users')),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_generation_jobs_source_id_sources')),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], name=op.f('fk_generation_jobs_topic_id_topics'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_generation_jobs'))
    )
    op.create_index('ix_generation_jobs_status_id', 'generation_jobs', ['status', 'id'], unique=False)
    op.add_column('items', sa.Column('source_id', sa.Integer(), nullable=True))
    op.create_index('ix_items_source_id', 'items', ['source_id'], unique=False)
    op.create_foreign_key(op.f('fk_items_source_id_sources'), 'items', 'sources', ['source_id'], ['id'])
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_items_source_id_sources'), 'items', type_='foreignkey')
    op.drop_index('ix_items_source_id', table_name='items')
    op.drop_column('items', 'source_id')
    op.drop_index('ix_generation_jobs_status_id', table_name='generation_jobs')
    op.drop_table('generation_jobs')
    op.drop_table('sources')
    # ### end Alembic commands ###
