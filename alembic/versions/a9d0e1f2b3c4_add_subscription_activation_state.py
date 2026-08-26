"""Add subscription activation state.

Revision ID: a9d0e1f2b3c4
Revises: h8c9d0e1f2a3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d0e1f2b3c4"
down_revision: str | None = "h8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "subscriptions",
        "group_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.add_column(
        "subscriptions",
        sa.Column("remaining_visits", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_remaining_visits_non_negative"),
        "subscriptions",
        "remaining_visits IS NULL OR remaining_visits >= 0",
    )


def downgrade() -> None:
    bind = op.get_bind()
    unlimited_count = bind.scalar(
        sa.text("SELECT count(*) FROM subscriptions WHERE group_id IS NULL")
    )
    if unlimited_count:
        raise RuntimeError(
            "Cannot make subscriptions.group_id NOT NULL while "
            "group-less subscriptions exist"
        )

    op.drop_constraint(
        op.f("ck_subscriptions_remaining_visits_non_negative"),
        "subscriptions",
        type_="check",
    )
    op.drop_column("subscriptions", "remaining_visits")
    op.alter_column(
        "subscriptions",
        "group_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
