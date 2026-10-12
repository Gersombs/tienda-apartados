"""Store photos uploaded from the CRM.

Revision ID: 20261011_03
Revises: 20260825_02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261011_03"
down_revision = "20260825_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploaded_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes > 0", name="ck_uploaded_images_size_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_uploaded_images_id"), "uploaded_images", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_uploaded_images_id"), table_name="uploaded_images")
    op.drop_table("uploaded_images")
