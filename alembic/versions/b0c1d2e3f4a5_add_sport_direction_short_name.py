"""add compact SportDirection display name

Revision ID: b0c1d2e3f4a5
Revises: a9d0e1f2b3c4
Create Date: 2026-08-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | None = "a9d0e1f2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional compact display names for sport directions."""
    op.add_column(
        "sport_directions",
        sa.Column("short_name", sa.String(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE sport_directions SET short_name = 'K1' "
            "WHERE name = 'Кикбоксинг'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE sport_directions SET short_name = 'MMA' "
            "WHERE name = 'MMA'"
        )
    )


def downgrade() -> None:
    """Remove only the compact display-name column."""
    op.drop_column("sport_directions", "short_name")
