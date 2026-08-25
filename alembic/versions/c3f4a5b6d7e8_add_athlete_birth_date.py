"""add Athlete birth date

Revision ID: c3f4a5b6d7e8
Revises: 9b5a2c7e1d4f
Create Date: 2026-08-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f4a5b6d7e8"
down_revision: str | None = "9b5a2c7e1d4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable date for compatibility with existing Athlete flows."""
    op.add_column(
        "athletes",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Remove Athlete birth date."""
    op.drop_column("athletes", "birth_date")
