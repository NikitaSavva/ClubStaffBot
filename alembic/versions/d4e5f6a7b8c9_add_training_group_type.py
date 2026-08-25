"""add TrainingGroup type and optional trainer

Revision ID: d4e5f6a7b8c9
Revises: c3f4a5b6d7e8
Create Date: 2026-08-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3f4a5b6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRAINING_GROUP_TYPE = postgresql.ENUM(
    "REGULAR",
    "MINI",
    name="training_group_type",
)


def upgrade() -> None:
    """Add an explicit group type and allow trainer assignment later."""
    TRAINING_GROUP_TYPE.create(op.get_bind())
    op.add_column(
        "training_groups",
        sa.Column("group_type", TRAINING_GROUP_TYPE, nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE training_groups "
            "SET group_type = CAST('REGULAR' AS training_group_type) "
            "WHERE group_type IS NULL"
        )
    )
    op.alter_column(
        "training_groups",
        "group_type",
        existing_type=TRAINING_GROUP_TYPE,
        nullable=False,
    )
    op.alter_column(
        "training_groups",
        "trainer_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    """Restore the original TrainingGroup schema."""
    op.alter_column(
        "training_groups",
        "trainer_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("training_groups", "group_type")
    TRAINING_GROUP_TYPE.drop(op.get_bind())
