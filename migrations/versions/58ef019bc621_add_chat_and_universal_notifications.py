"""add chat and universal notifications

Revision ID: 58ef019bc621
Revises: 2a7ef091c654
"""
from alembic import op
import sqlalchemy as sa


revision = "58ef019bc621"
down_revision = "2a7ef091c654"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notification") as batch_op:
        batch_op.alter_column("student_id", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("date", existing_type=sa.Date(), nullable=True)
        batch_op.add_column(sa.Column("kind", sa.String(40), nullable=False, server_default="mention"))
        batch_op.add_column(sa.Column("target_url", sa.String(1000), nullable=True))
        batch_op.add_column(sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_notification_kind", ["kind"])

    op.create_table(
        "chat_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_name", sa.String(80), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_message_group_name", "chat_message", ["group_name"])
    op.create_table(
        "chat_reply",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_reply_message_id", "chat_reply", ["message_id"])


def downgrade():
    op.drop_table("chat_reply")
    op.drop_table("chat_message")
    op.execute("DELETE FROM notification WHERE student_id IS NULL OR date IS NULL")
    with op.batch_alter_table("notification") as batch_op:
        batch_op.drop_index("ix_notification_kind")
        batch_op.drop_column("read_at")
        batch_op.drop_column("target_url")
        batch_op.drop_column("kind")
        batch_op.alter_column("date", existing_type=sa.Date(), nullable=False)
        batch_op.alter_column("student_id", existing_type=sa.Integer(), nullable=False)
