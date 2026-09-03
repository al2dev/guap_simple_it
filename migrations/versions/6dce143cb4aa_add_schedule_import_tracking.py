"""add schedule import tracking

Revision ID: 6dce143cb4aa
Revises: 1be5021b2acc
"""
from alembic import op
import sqlalchemy as sa


revision = "6dce143cb4aa"
down_revision = "1be5021b2acc"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schedule_import",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=80), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("schedule_item_id", sa.Integer(), nullable=True),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["schedule_item_id"], ["schedule_item.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_item_id"),
    )
    op.create_index("ix_schedule_import_group_name", "schedule_import", ["group_name"])
    op.create_index("ix_schedule_import_period_start", "schedule_import", ["period_start"])
    op.create_index("ix_schedule_import_source_key", "schedule_import", ["source_key"], unique=True)


def downgrade():
    op.drop_index("ix_schedule_import_source_key", table_name="schedule_import")
    op.drop_index("ix_schedule_import_period_start", table_name="schedule_import")
    op.drop_index("ix_schedule_import_group_name", table_name="schedule_import")
    op.drop_table("schedule_import")
