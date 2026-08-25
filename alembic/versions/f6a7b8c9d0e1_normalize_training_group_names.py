"""normalize TrainingGroup names

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-25 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move repeated TrainingGroup names into a normalized lookup table."""
    op.create_table(
        "group_names",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_group_names")),
        sa.UniqueConstraint("name", name=op.f("uq_group_names_name")),
    )
    op.add_column(
        "training_groups",
        sa.Column("name_id", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "INSERT INTO group_names (name) "
            "SELECT DISTINCT name FROM training_groups ORDER BY name"
        )
    )
    op.execute(
        sa.text(
            "UPDATE training_groups AS training_group "
            "SET name_id = group_name.id "
            "FROM group_names AS group_name "
            "WHERE training_group.name = group_name.name"
        )
    )
    op.alter_column(
        "training_groups",
        "name_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        op.f("fk_training_groups_name_id_group_names"),
        "training_groups",
        "group_names",
        ["name_id"],
        ["id"],
    )
    op.drop_column("training_groups", "name")


def downgrade() -> None:
    """Restore names directly on TrainingGroup rows."""
    op.add_column(
        "training_groups",
        sa.Column("name", sa.String(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE training_groups AS training_group "
            "SET name = group_name.name "
            "FROM group_names AS group_name "
            "WHERE training_group.name_id = group_name.id"
        )
    )
    op.alter_column(
        "training_groups",
        "name",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_constraint(
        op.f("fk_training_groups_name_id_group_names"),
        "training_groups",
        type_="foreignkey",
    )
    op.drop_column("training_groups", "name_id")
    op.drop_table("group_names")
