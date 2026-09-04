"""add schedule address

Revision ID: 2a7ef091c654
Revises: 6dce143cb4aa
"""
from alembic import op
import sqlalchemy as sa


revision = "2a7ef091c654"
down_revision = "6dce143cb4aa"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("schedule_item") as batch_op:
        batch_op.add_column(sa.Column("address", sa.String(length=160), nullable=True))


def downgrade():
    with op.batch_alter_table("schedule_item") as batch_op:
        batch_op.drop_column("address")
