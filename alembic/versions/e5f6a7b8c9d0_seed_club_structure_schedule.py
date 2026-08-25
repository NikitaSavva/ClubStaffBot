"""seed club structure and schedule

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-25 12:30:00.000000

"""

from collections.abc import Sequence
from datetime import time
from typing import TypedDict

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONDAY = 0
TUESDAY = 1
WEDNESDAY = 2
THURSDAY = 3
FRIDAY = 4
SATURDAY = 5

Schedule = tuple[tuple[int, time, time], ...]


class DirectionSeed(TypedDict):
    code: str
    name: str


class GroupSeed(TypedDict):
    direction: str
    name: str
    group_type: str
    schedule: Schedule


DIRECTIONS: tuple[DirectionSeed, ...] = (
    {"code": "KICKBOXING", "name": "Кикбоксинг"},
    {"code": "MMA", "name": "MMA"},
)

TRAINING_GROUP_TYPE = postgresql.ENUM(
    "REGULAR",
    "MINI",
    name="training_group_type",
    create_type=False,
)

GROUPS: tuple[GroupSeed, ...] = (
    {
        "direction": "Кикбоксинг",
        "name": "Сборная",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(16, 0), time(17, 30))
            for weekday in range(MONDAY, SATURDAY + 1)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Дети 9–14 лет",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(9, 0), time(10, 30))
            for weekday in (MONDAY, WEDNESDAY, FRIDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Мини-группа",
        "group_type": "MINI",
        "schedule": tuple(
            (weekday, time(14, 0), time(15, 30))
            for weekday in (MONDAY, WEDNESDAY, FRIDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Подростки",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(17, 30), time(19, 0))
            for weekday in (MONDAY, WEDNESDAY, FRIDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Взрослые",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(19, 0), time(20, 30))
            for weekday in (MONDAY, WEDNESDAY, FRIDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Взрослые",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(8, 30), time(10, 0))
            for weekday in (TUESDAY, THURSDAY, SATURDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Девушки",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(10, 0), time(11, 0))
            for weekday in (TUESDAY, THURSDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Дети 6–9 лет",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(17, 30), time(18, 45))
            for weekday in (TUESDAY, THURSDAY, SATURDAY)
        ),
    },
    {
        "direction": "Кикбоксинг",
        "name": "Девушки",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(18, 45), time(20, 0))
            for weekday in (TUESDAY, THURSDAY, SATURDAY)
        ),
    },
    {
        "direction": "MMA",
        "name": "Взрослые",
        "group_type": "REGULAR",
        "schedule": tuple(
            (weekday, time(20, 0), time(21, 30))
            for weekday in (TUESDAY, THURSDAY, SATURDAY)
        ),
    },
)

sport_directions = sa.table(
    "sport_directions",
    sa.column("id", sa.Integer()),
    sa.column("code", sa.String()),
    sa.column("name", sa.String()),
    sa.column("is_active", sa.Boolean()),
)
training_groups = sa.table(
    "training_groups",
    sa.column("id", sa.Integer()),
    sa.column("direction_id", sa.Integer()),
    sa.column("trainer_id", sa.Integer()),
    sa.column("name", sa.String()),
    sa.column("group_type", TRAINING_GROUP_TYPE),
    sa.column("is_active", sa.Boolean()),
)
schedule_rules = sa.table(
    "schedule_rules",
    sa.column("id", sa.Integer()),
    sa.column("group_id", sa.Integer()),
    sa.column("weekday", sa.SmallInteger()),
    sa.column("start_time", sa.Time()),
    sa.column("end_time", sa.Time()),
    sa.column("valid_from", sa.Date()),
    sa.column("valid_until", sa.Date()),
    sa.column("is_active", sa.Boolean()),
)


def upgrade() -> None:
    """Create the fixed MVP club configuration."""
    connection = op.get_bind()
    direction_ids = {
        seed["name"]: _resolve_direction(connection, seed)
        for seed in DIRECTIONS
    }

    for seed in GROUPS:
        group_id = connection.execute(
            sa.insert(training_groups)
            .values(
                direction_id=direction_ids[seed["direction"]],
                trainer_id=None,
                name=seed["name"],
                group_type=seed["group_type"],
                is_active=True,
            )
            .returning(training_groups.c.id)
        ).scalar_one()
        connection.execute(
            sa.insert(schedule_rules),
            [
                {
                    "group_id": group_id,
                    "weekday": weekday,
                    "start_time": start_time,
                    "end_time": end_time,
                    "valid_from": None,
                    "valid_until": None,
                    "is_active": True,
                }
                for weekday, start_time, end_time in seed["schedule"]
            ],
        )


def downgrade() -> None:
    """Remove only the fixed MVP configuration when it is still intact."""
    connection = op.get_bind()

    for seed in reversed(GROUPS):
        group_id = _find_seeded_group_id(connection, seed)
        connection.execute(
            sa.delete(schedule_rules).where(
                schedule_rules.c.group_id == group_id
            )
        )
        connection.execute(
            sa.delete(training_groups).where(training_groups.c.id == group_id)
        )

    for seed in reversed(DIRECTIONS):
        direction_id = connection.execute(
            sa.select(sport_directions.c.id).where(
                sport_directions.c.code == seed["code"],
                sport_directions.c.name == seed["name"],
            )
        ).scalar_one_or_none()
        if direction_id is None:
            continue
        has_groups = connection.execute(
            sa.select(training_groups.c.id)
            .where(training_groups.c.direction_id == direction_id)
            .limit(1)
        ).first()
        if has_groups is None:
            connection.execute(
                sa.delete(sport_directions).where(
                    sport_directions.c.id == direction_id
                )
            )


def _resolve_direction(
    connection: Connection,
    seed: DirectionSeed,
) -> int:
    rows = connection.execute(
        sa.select(
            sport_directions.c.id,
            sport_directions.c.code,
            sport_directions.c.name,
            sport_directions.c.is_active,
        ).where(
            sa.or_(
                sport_directions.c.code == seed["code"],
                sport_directions.c.name == seed["name"],
            )
        )
    ).mappings().all()

    matching_name = [row for row in rows if row["name"] == seed["name"]]
    matching_code = [row for row in rows if row["code"] == seed["code"]]
    if len(matching_name) > 1 or len(matching_code) > 1:
        raise RuntimeError(
            f"Ambiguous SportDirection seed target: {seed['name']}"
        )
    if matching_name:
        direction = matching_name[0]
        if matching_code and matching_code[0]["id"] != direction["id"]:
            raise RuntimeError(
                f"SportDirection code/name conflict: {seed['code']} / "
                f"{seed['name']}"
            )
        if not direction["is_active"]:
            raise RuntimeError(
                f"SportDirection {seed['name']} exists but is inactive"
            )
        return int(direction["id"])
    if matching_code:
        raise RuntimeError(
            f"SportDirection code {seed['code']} already has another name"
        )

    return int(
        connection.execute(
            sa.insert(sport_directions)
            .values(
                code=seed["code"],
                name=seed["name"],
                is_active=True,
            )
            .returning(sport_directions.c.id)
        ).scalar_one()
    )


def _find_seeded_group_id(
    connection: Connection,
    seed: GroupSeed,
) -> int:
    candidate_ids = connection.execute(
        sa.select(training_groups.c.id)
        .select_from(
            training_groups.join(
                sport_directions,
                training_groups.c.direction_id == sport_directions.c.id,
            )
        )
        .where(
            sport_directions.c.name == seed["direction"],
            training_groups.c.name == seed["name"],
            training_groups.c.group_type == seed["group_type"],
            training_groups.c.trainer_id.is_(None),
            training_groups.c.is_active.is_(True),
        )
        .order_by(training_groups.c.id.desc())
    ).scalars().all()
    expected_schedule = set(seed["schedule"])

    for group_id in candidate_ids:
        rules = connection.execute(
            sa.select(
                schedule_rules.c.weekday,
                schedule_rules.c.start_time,
                schedule_rules.c.end_time,
                schedule_rules.c.valid_from,
                schedule_rules.c.valid_until,
                schedule_rules.c.is_active,
            ).where(schedule_rules.c.group_id == group_id)
        ).all()
        actual_schedule = {
            (weekday, start_time, end_time)
            for (
                weekday,
                start_time,
                end_time,
                valid_from,
                valid_until,
                is_active,
            ) in rules
            if valid_from is None and valid_until is None and is_active
        }
        if len(rules) == len(expected_schedule) and actual_schedule == expected_schedule:
            return int(group_id)

    raise RuntimeError(
        "Seeded TrainingGroup is missing or was modified: "
        f"{seed['direction']} / {seed['name']} / {seed['schedule']}"
    )
