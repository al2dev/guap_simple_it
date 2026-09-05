"""add authenticated page views

Revision ID: 7b2d931ea640
Revises: 58ef019bc621
"""
from alembic import op
import sqlalchemy as sa

revision = "7b2d931ea640"
down_revision = "58ef019bc621"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "page_view",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_view_created_at", "page_view", ["created_at"])
    op.create_index("ix_page_view_user_created", "page_view", ["user_id", "created_at"])


def downgrade():
    op.drop_table("page_view")
