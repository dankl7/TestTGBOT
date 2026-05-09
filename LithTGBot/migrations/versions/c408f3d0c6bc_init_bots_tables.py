"""init bots tables

Revision ID: c408f3d0c6bc
Revises: 
Create Date: 2026-05-04 20:45:47.698012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c408f3d0c6bc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tracked_products',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('last_seen_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('last_notified_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_id', name='uq_tracked_user_product')
    )
    op.create_index('idx_tracked_products_user_id', 'tracked_products', ['user_id'])
    op.create_index('idx_tracked_products_product_id', 'tracked_products', ['product_id'])
    op.create_index('idx_tracked_products_active', 'tracked_products', ['is_active'])

    op.create_table(
        'user_search_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('query', sa.String(length=500), nullable=False),
        sa.Column('normalized_query', sa.String(length=500), nullable=True),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('final_price', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('results_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.execute('CREATE INDEX idx_user_search_history_user_created ON user_search_history(user_id, created_at DESC)')
    op.execute('CREATE INDEX idx_user_search_history_query_created ON user_search_history(query, created_at DESC)')
    op.create_index('idx_user_search_history_product_id', 'user_search_history', ['product_id'])
    op.execute('CREATE INDEX idx_user_search_history_query_count ON user_search_history(query, results_count DESC)')



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_search_history')
    op.drop_table('tracked_products')

