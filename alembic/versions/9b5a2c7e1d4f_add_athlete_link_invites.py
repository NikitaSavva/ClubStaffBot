"""add athlete account-link invites

Revision ID: 9b5a2c7e1d4f
Revises: 1e1a708c7c2e
Create Date: 2026-08-20 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9b5a2c7e1d4f"
down_revision: str | None = "1e1a708c7c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOT_INVITE_PURPOSE = postgresql.ENUM(
    "REGISTRATION",
    "ATHLETE_LINK",
    name="bot_invite_purpose",
)


def upgrade() -> None:
    """Add purpose, Athlete target, and one-time consumption state."""
    BOT_INVITE_PURPOSE.create(op.get_bind())
    op.add_column(
        "bot_invites",
        sa.Column(
            "purpose",
            BOT_INVITE_PURPOSE,
            server_default=sa.text("'REGISTRATION'"),
            nullable=False,
        ),
    )
    op.add_column(
        "bot_invites",
        sa.Column("athlete_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "bot_invites",
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_bot_invites_athlete_id_athletes",
        "bot_invites",
        "athletes",
        ["athlete_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_bot_invites_purpose_athlete"),
        "bot_invites",
        "(purpose = 'REGISTRATION' AND athlete_id IS NULL) OR "
        "(purpose = 'ATHLETE_LINK' AND athlete_id IS NOT NULL)",
    )
    op.alter_column("bot_invites", "purpose", server_default=None)


def downgrade() -> None:
    """Remove athlete account-link invite fields."""
    op.drop_constraint(
        op.f("ck_bot_invites_purpose_athlete"),
        "bot_invites",
        type_="check",
    )
    op.drop_constraint(
        "fk_bot_invites_athlete_id_athletes",
        "bot_invites",
        type_="foreignkey",
    )
    op.drop_column("bot_invites", "consumed_at")
    op.drop_column("bot_invites", "athlete_id")
    op.drop_column("bot_invites", "purpose")
    BOT_INVITE_PURPOSE.drop(op.get_bind())
