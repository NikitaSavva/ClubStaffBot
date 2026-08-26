"""seed SubscriptionPlan configuration

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-08-26 12:30:00.000000

"""

from collections.abc import Sequence
from decimal import Decimal
from typing import TypedDict

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h8c9d0e1f2a3"
down_revision: str | None = "g7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class PlanSeed(TypedDict):
    code: str
    name: str
    visit_limit: int | None
    duration_months: int
    price: Decimal
    is_unlimited: bool
    access_scope: str
    required_group_type: str | None
    is_active: bool


PLANS: tuple[PlanSeed, ...] = (
    {
        "code": "8_VISITS",
        "name": "8 посещений",
        "visit_limit": 8,
        "duration_months": 1,
        "price": Decimal("4000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": None,
        "is_active": True,
    },
    {
        "code": "12_VISITS",
        "name": "12 посещений",
        "visit_limit": 12,
        "duration_months": 1,
        "price": Decimal("6000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": None,
        "is_active": True,
    },
    {
        "code": "MINI_GROUP",
        "name": "Мини-группа",
        "visit_limit": 12,
        "duration_months": 1,
        "price": Decimal("8000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": "MINI",
        "is_active": True,
    },
    {
        "code": "UNLIMITED",
        "name": "Безлимит",
        "visit_limit": None,
        "duration_months": 1,
        "price": Decimal("10000"),
        "is_unlimited": True,
        "access_scope": "ALL_REGULAR_GROUPS",
        "required_group_type": None,
        "is_active": True,
    },
    {
        "code": "3_MONTHS",
        "name": "3 месяца",
        "visit_limit": 36,
        "duration_months": 3,
        "price": Decimal("18000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": None,
        "is_active": True,
    },
    {
        "code": "6_MONTHS",
        "name": "6 месяцев",
        "visit_limit": 72,
        "duration_months": 6,
        "price": Decimal("36000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": None,
        "is_active": True,
    },
    {
        "code": "12_MONTHS",
        "name": "12 месяцев",
        "visit_limit": 144,
        "duration_months": 12,
        "price": Decimal("72000"),
        "is_unlimited": False,
        "access_scope": "SPECIFIC_GROUP",
        "required_group_type": None,
        "is_active": True,
    },
)

SUBSCRIPTION_ACCESS_SCOPE = postgresql.ENUM(
    "SPECIFIC_GROUP",
    "ALL_REGULAR_GROUPS",
    name="subscription_access_scope",
    create_type=False,
)
TRAINING_GROUP_TYPE = postgresql.ENUM(
    "REGULAR",
    "MINI",
    name="training_group_type",
    create_type=False,
)
subscription_plans = sa.table(
    "subscription_plans",
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("visit_limit", sa.Integer()),
    sa.column("duration_months", sa.Integer()),
    sa.column("price", sa.Numeric()),
    sa.column("is_unlimited", sa.Boolean()),
    sa.column("access_scope", SUBSCRIPTION_ACCESS_SCOPE),
    sa.column("required_group_type", TRAINING_GROUP_TYPE),
    sa.column("is_active", sa.Boolean()),
)


def upgrade() -> None:
    """Insert the fixed MVP SubscriptionPlan configuration."""
    connection = op.get_bind()
    codes = tuple(plan["code"] for plan in PLANS)
    names = tuple(plan["name"] for plan in PLANS)
    conflicts = connection.execute(
        sa.select(subscription_plans.c.code, subscription_plans.c.name).where(
            sa.or_(
                subscription_plans.c.code.in_(codes),
                subscription_plans.c.name.in_(names),
            )
        )
    ).mappings().all()
    if conflicts:
        formatted = ", ".join(
            f"{row['code'] or '<no code>'}: {row['name']}"
            for row in conflicts
        )
        raise RuntimeError(
            "SubscriptionPlan seed conflicts with existing rows: "
            f"{formatted}"
        )

    connection.execute(sa.insert(subscription_plans), list(PLANS))


def downgrade() -> None:
    """Remove only the fixed MVP SubscriptionPlan configuration."""
    codes = tuple(plan["code"] for plan in PLANS)
    op.get_bind().execute(
        sa.delete(subscription_plans).where(
            subscription_plans.c.code.in_(codes)
        )
    )
