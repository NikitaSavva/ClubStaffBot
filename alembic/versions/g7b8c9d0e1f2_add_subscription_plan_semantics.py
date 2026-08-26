"""add SubscriptionPlan semantics

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBSCRIPTION_ACCESS_SCOPE = postgresql.ENUM(
    "SPECIFIC_GROUP",
    "ALL_REGULAR_GROUPS",
    name="subscription_access_scope",
)
TRAINING_GROUP_TYPE = postgresql.ENUM(
    "REGULAR",
    "MINI",
    name="training_group_type",
    create_type=False,
)


def upgrade() -> None:
    """Add explicit access and calendar-duration metadata to plans."""
    connection = op.get_bind()
    existing_plans = connection.execute(
        sa.text(
            "SELECT plan.id, plan.name, plan.duration_days, "
            "count(subscription.id) AS subscription_count "
            "FROM subscription_plans AS plan "
            "LEFT JOIN subscriptions AS subscription "
            "ON subscription.plan_id = plan.id "
            "GROUP BY plan.id, plan.name, plan.duration_days "
            "ORDER BY plan.id"
        )
    ).mappings().all()
    if existing_plans:
        details = "; ".join(
            f"id={row['id']}, name={row['name']!r}, "
            f"duration_days={row['duration_days']}, "
            f"subscription_count={row['subscription_count']}"
            for row in existing_plans
        )
        raise RuntimeError(
            "Cannot replace duration_days with calendar duration_months "
            "while SubscriptionPlan rows exist: "
            f"{details}"
        )

    SUBSCRIPTION_ACCESS_SCOPE.create(connection)
    op.drop_column("subscription_plans", "duration_days")
    op.add_column(
        "subscription_plans",
        sa.Column("duration_months", sa.Integer(), nullable=False),
    )
    op.add_column(
        "subscription_plans",
        sa.Column("code", sa.String(), nullable=False),
    )
    op.create_unique_constraint(
        op.f("uq_subscription_plans_code"),
        "subscription_plans",
        ["code"],
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "access_scope",
            SUBSCRIPTION_ACCESS_SCOPE,
            nullable=False,
        ),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "required_group_type",
            TRAINING_GROUP_TYPE,
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Restore the legacy day-based SubscriptionPlan schema."""
    connection = op.get_bind()
    existing_plans = connection.execute(
        sa.text(
            "SELECT id, code, name, duration_months "
            "FROM subscription_plans ORDER BY id"
        )
    ).mappings().all()
    if existing_plans:
        details = "; ".join(
            f"id={row['id']}, code={row['code']!r}, "
            f"name={row['name']!r}, "
            f"duration_months={row['duration_months']}"
            for row in existing_plans
        )
        raise RuntimeError(
            "Cannot restore duration_days while calendar-month "
            f"SubscriptionPlan rows still exist: {details}"
        )

    op.add_column(
        "subscription_plans",
        sa.Column("duration_days", sa.Integer(), nullable=False),
    )
    op.drop_column("subscription_plans", "required_group_type")
    op.drop_column("subscription_plans", "access_scope")
    op.drop_column("subscription_plans", "duration_months")
    op.drop_constraint(
        op.f("uq_subscription_plans_code"),
        "subscription_plans",
        type_="unique",
    )
    op.drop_column("subscription_plans", "code")
    SUBSCRIPTION_ACCESS_SCOPE.drop(connection)
