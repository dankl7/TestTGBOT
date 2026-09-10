"""create correct schema for max bridge

Revision ID: a1b2c3d4e5f6
Revises: 9ad7d79e0eb5
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9ad7d79e0eb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old broken tables from incorrect migration
    op.execute("DROP TABLE IF EXISTS project_users CASCADE")
    op.execute("DROP TABLE IF EXISTS mass_mailing_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS mass_mailing_targets CASCADE")
    # Drop old projects table if it exists (different schema from models.py)
    op.execute("DROP TABLE IF EXISTS projects CASCADE")

    # Create users table
    op.create_table(
        'users',
        sa.Column('telegram_id', sa.BigInteger(), primary_key=True),
        sa.Column('timezone', sa.Integer(), server_default='-3'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create messages table (managed by app, no cascade delete)
    op.create_table(
        'messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('media_type', sa.String(50), nullable=True),
        sa.Column('media_path', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create projects table
    op.create_table(
        'projects',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('owner_id', sa.BigInteger(), sa.ForeignKey('users.telegram_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('auth_token', sa.Text(), nullable=False),
        sa.Column('default_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create groups table
    op.create_table(
        'groups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('max_group_id', sa.BigInteger(), nullable=False),
        sa.Column('custom_message_id', UUID(as_uuid=True), sa.ForeignKey('messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create schedules table
    op.create_table(
        'schedules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_id', UUID(as_uuid=True), sa.ForeignKey('groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schedule_type', sa.String(20), nullable=False),
        sa.Column('schedule_value', JSONB(), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create logs table
    op.create_table(
        'logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('group_id', UUID(as_uuid=True), sa.ForeignKey('groups.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.telegram_id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('logs')
    op.drop_table('schedules')
    op.drop_table('groups')
    op.drop_table('projects')
    op.drop_table('messages')
    op.drop_table('users')
