import asyncio
from collections import Counter
from datetime import time
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from infrastructure.database.session import create_engine

PROJECT_ROOT = Path(__file__).parents[3]
PRE_CLUB_SEED_REVISION = "9b5a2c7e1d4f"

MONDAY = 0
TUESDAY = 1
WEDNESDAY = 2
THURSDAY = 3
FRIDAY = 4
SATURDAY = 5
SUNDAY = 6

NormalizedScheduleItem = tuple[str, str, int, time, time]


def _schedule(
    direction: str,
    group: str,
    weekdays: tuple[int, ...],
    start_time: time,
    end_time: time,
) -> set[NormalizedScheduleItem]:
    return {
        (direction, group, weekday, start_time, end_time)
        for weekday in weekdays
    }


EXPECTED_SCHEDULE = set().union(
    _schedule(
        "Кикбоксинг",
        "Сборная",
        (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY),
        time(16, 0),
        time(17, 30),
    ),
    _schedule(
        "Кикбоксинг",
        "Дети 9–14 лет",
        (MONDAY, WEDNESDAY, FRIDAY),
        time(9, 0),
        time(10, 30),
    ),
    _schedule(
        "Кикбоксинг",
        "Мини-группа",
        (MONDAY, WEDNESDAY, FRIDAY),
        time(14, 0),
        time(15, 30),
    ),
    _schedule(
        "Кикбоксинг",
        "Подростки",
        (MONDAY, WEDNESDAY, FRIDAY),
        time(17, 30),
        time(19, 0),
    ),
    _schedule(
        "Кикбоксинг",
        "Взрослые",
        (MONDAY, WEDNESDAY, FRIDAY),
        time(19, 0),
        time(20, 30),
    ),
    _schedule(
        "Кикбоксинг",
        "Взрослые",
        (TUESDAY, THURSDAY, SATURDAY),
        time(8, 30),
        time(10, 0),
    ),
    _schedule(
        "Кикбоксинг",
        "Девушки",
        (TUESDAY, THURSDAY),
        time(10, 0),
        time(11, 0),
    ),
    _schedule(
        "Кикбоксинг",
        "Дети 6–9 лет",
        (TUESDAY, THURSDAY, SATURDAY),
        time(17, 30),
        time(18, 45),
    ),
    _schedule(
        "Кикбоксинг",
        "Девушки",
        (TUESDAY, THURSDAY, SATURDAY),
        time(18, 45),
        time(20, 0),
    ),
    _schedule(
        "MMA",
        "Взрослые",
        (TUESDAY, THURSDAY, SATURDAY),
        time(20, 0),
        time(21, 30),
    ),
)
EXPECTED_GROUP_NAMES = {
    "Сборная",
    "Дети 9–14 лет",
    "Мини-группа",
    "Подростки",
    "Взрослые",
    "Девушки",
    "Дети 6–9 лет",
}


async def test_seeded_club_structure_and_schedule(
    db_session: AsyncSession,
) -> None:
    await _assert_seeded_club_structure(db_session)


def test_migration_round_trip_and_models_match_head(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, PRE_CLUB_SEED_REVISION)
    athlete_public_id = uuid4()
    asyncio.run(_insert_legacy_data(database_url, athlete_public_id))

    command.upgrade(config, "head")
    asyncio.run(_assert_legacy_data_at_head(database_url, athlete_public_id))
    asyncio.run(_assert_seeded_data_at_url(database_url))
    command.check(config)

    command.downgrade(config, PRE_CLUB_SEED_REVISION)
    asyncio.run(_assert_legacy_data_at_prior_revision(database_url))

    command.upgrade(config, "head")
    asyncio.run(_assert_legacy_data_at_head(database_url, athlete_public_id))
    asyncio.run(_assert_seeded_data_at_url(database_url))
    command.check(config)


async def _insert_legacy_data(
    database_url: str,
    athlete_public_id: UUID,
) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO athletes "
                    "(athlete_public_id, user_id, first_name, last_name, "
                    "phone, is_active) "
                    "VALUES (CAST(:athlete_public_id AS UUID), NULL, "
                    ":first_name, :last_name, NULL, true)"
                ),
                {
                    "athlete_public_id": str(athlete_public_id),
                    "first_name": "Legacy",
                    "last_name": "Athlete",
                },
            )
            trainer_id = (
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(telegram_id, username, first_name, last_name, "
                        "is_active, registered_at, last_seen_at) "
                        "VALUES (900000001, NULL, 'Legacy', 'Trainer', true, "
                        "now(), now()) RETURNING id"
                    )
                )
            ).scalar_one()
            boxing_id = (
                await connection.execute(
                    text(
                        "INSERT INTO sport_directions (code, name, is_active) "
                        "VALUES ('BOXING', 'Бокс', true) RETURNING id"
                    )
                )
            ).scalar_one()
            mma_id = (
                await connection.execute(
                    text(
                        "INSERT INTO sport_directions "
                        "(code, name, is_active) "
                        "VALUES ('LEGACY_MMA', 'MMA', true) RETURNING id"
                    )
                )
            ).scalar_one()
            boxing_group_id = (
                await connection.execute(
                    text(
                        "INSERT INTO training_groups "
                        "(direction_id, trainer_id, name, is_active) "
                        "VALUES (:direction_id, :trainer_id, "
                        "'Legacy group', true) RETURNING id"
                    ),
                    {"direction_id": boxing_id, "trainer_id": trainer_id},
                )
            ).scalar_one()
            mma_group_id = (
                await connection.execute(
                    text(
                        "INSERT INTO training_groups "
                        "(direction_id, trainer_id, name, is_active) "
                        "VALUES (:direction_id, :trainer_id, "
                        "'Взрослые', true) RETURNING id"
                    ),
                    {"direction_id": mma_id, "trainer_id": trainer_id},
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO schedule_rules "
                    "(group_id, weekday, start_time, end_time, valid_from, "
                    "valid_until, is_active) "
                    "VALUES (:group_id, :weekday, '12:00', '13:00', NULL, "
                    "NULL, true)"
                ),
                [
                    {"group_id": boxing_group_id, "weekday": SUNDAY},
                    {"group_id": mma_group_id, "weekday": SUNDAY},
                ],
            )
    finally:
        await engine.dispose()


async def _assert_seeded_data_at_url(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            await _assert_seeded_club_structure(connection)
    finally:
        await engine.dispose()


async def _assert_seeded_club_structure(
    connection: AsyncConnection | AsyncSession,
) -> None:
    directions = (
        await connection.execute(
            text(
                "SELECT code, name, is_active FROM sport_directions "
                "WHERE name IN ('Кикбоксинг', 'MMA') ORDER BY name"
            )
        )
    ).mappings().all()
    assert len(directions) == 2
    assert {row["name"] for row in directions} == {"Кикбоксинг", "MMA"}
    assert all(row["is_active"] for row in directions)

    schema = (
        await connection.execute(
            text(
                "SELECT column_name, is_nullable, column_default, udt_name "
                "FROM information_schema.columns "
                "WHERE table_name = 'training_groups' AND "
                "column_name IN "
                "('group_type', 'trainer_id', 'name', 'name_id')"
            )
        )
    ).mappings().all()
    columns = {row["column_name"]: row for row in schema}
    assert columns["group_type"]["is_nullable"] == "NO"
    assert columns["group_type"]["column_default"] is None
    assert columns["group_type"]["udt_name"] == "training_group_type"
    assert columns["trainer_id"]["is_nullable"] == "YES"
    assert columns["name_id"]["is_nullable"] == "NO"
    assert "name" not in columns

    names = (
        await connection.execute(
            text(
                "SELECT id, name FROM group_names "
                "WHERE name IN ('Сборная', 'Дети 9–14 лет', "
                "'Мини-группа', 'Подростки', 'Взрослые', 'Девушки', "
                "'Дети 6–9 лет')"
            )
        )
    ).mappings().all()
    assert len(names) == len(EXPECTED_GROUP_NAMES) == 7
    assert {row["name"] for row in names} == EXPECTED_GROUP_NAMES

    groups = (
        await connection.execute(
            text(
                "SELECT g.id, d.name AS direction, group_name.id AS name_id, "
                "group_name.name, "
                "CAST(g.group_type AS VARCHAR) AS group_type, g.trainer_id "
                "FROM training_groups AS g "
                "JOIN sport_directions AS d ON d.id = g.direction_id "
                "JOIN group_names AS group_name ON group_name.id = g.name_id "
                "WHERE g.trainer_id IS NULL AND "
                "d.name IN ('Кикбоксинг', 'MMA') "
                "ORDER BY g.id"
            )
        )
    ).mappings().all()
    assert len(groups) == 10
    assert Counter(group["group_type"] for group in groups) == {
        "REGULAR": 9,
        "MINI": 1,
    }
    assert all(group["trainer_id"] is None for group in groups)
    assert [
        (group["direction"], group["name"])
        for group in groups
        if group["group_type"] == "MINI"
    ] == [("Кикбоксинг", "Мини-группа")]
    group_names = Counter(
        (group["direction"], group["name"]) for group in groups
    )
    assert group_names[("Кикбоксинг", "Взрослые")] == 2
    assert group_names[("Кикбоксинг", "Девушки")] == 2
    assert len(
        {group["name_id"] for group in groups if group["name"] == "Взрослые"}
    ) == 1
    assert len(
        {group["name_id"] for group in groups if group["name"] == "Девушки"}
    ) == 1

    rules = (
        await connection.execute(
            text(
                "SELECT d.name AS direction, group_name.name AS group_name, "
                "r.weekday, r.start_time, r.end_time, r.valid_from, "
                "r.valid_until, r.is_active "
                "FROM schedule_rules AS r "
                "JOIN training_groups AS g ON g.id = r.group_id "
                "JOIN group_names AS group_name ON group_name.id = g.name_id "
                "JOIN sport_directions AS d ON d.id = g.direction_id "
                "WHERE g.trainer_id IS NULL AND "
                "d.name IN ('Кикбоксинг', 'MMA')"
            )
        )
    ).mappings().all()
    actual_schedule = {
        (
            rule["direction"],
            rule["group_name"],
            rule["weekday"],
            rule["start_time"],
            rule["end_time"],
        )
        for rule in rules
    }
    assert len(rules) == len(EXPECTED_SCHEDULE) == 32
    assert actual_schedule == EXPECTED_SCHEDULE
    assert all(rule["weekday"] != SUNDAY for rule in rules)
    assert all(rule["valid_from"] is None for rule in rules)
    assert all(rule["valid_until"] is None for rule in rules)
    assert all(rule["is_active"] for rule in rules)


async def _assert_legacy_data_at_head(
    database_url: str,
    athlete_public_id: UUID,
) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            athlete = (
                await connection.execute(
                    text(
                        "SELECT first_name, last_name, birth_date, user_id "
                        "FROM athletes WHERE athlete_public_id = "
                        "CAST(:athlete_public_id AS UUID)"
                    ),
                    {"athlete_public_id": str(athlete_public_id)},
                )
            ).one()
            groups = (
                await connection.execute(
                    text(
                        "SELECT d.code AS direction_code, "
                        "d.name AS direction_name, "
                        "group_name.name AS group_name, "
                        "CAST(g.group_type AS VARCHAR) AS group_type, "
                        "g.trainer_id, r.weekday, r.start_time, r.end_time "
                        "FROM training_groups AS g "
                        "JOIN group_names AS group_name "
                        "ON group_name.id = g.name_id "
                        "JOIN sport_directions AS d ON d.id = g.direction_id "
                        "JOIN schedule_rules AS r ON r.group_id = g.id "
                        "WHERE d.code IN ('BOXING', 'LEGACY_MMA') "
                        "AND g.trainer_id IS NOT NULL ORDER BY d.code"
                    )
                )
            ).mappings().all()
            mma_code = (
                await connection.execute(
                    text("SELECT code FROM sport_directions WHERE name = 'MMA'")
                )
            ).scalar_one()
        assert athlete == ("Legacy", "Athlete", None, None)
        assert [
            (
                group["direction_code"],
                group["direction_name"],
                group["group_name"],
                group["group_type"],
                group["weekday"],
                group["start_time"],
                group["end_time"],
            )
            for group in groups
        ] == [
            (
                "BOXING",
                "Бокс",
                "Legacy group",
                "REGULAR",
                SUNDAY,
                time(12, 0),
                time(13, 0),
            ),
            (
                "LEGACY_MMA",
                "MMA",
                "Взрослые",
                "REGULAR",
                SUNDAY,
                time(12, 0),
                time(13, 0),
            ),
        ]
        assert all(group["trainer_id"] is not None for group in groups)
        assert mma_code == "LEGACY_MMA"
    finally:
        await engine.dispose()


async def _assert_legacy_data_at_prior_revision(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            groups = (
                await connection.execute(
                    text(
                        "SELECT d.code, g.name AS group_name, g.trainer_id, "
                        "r.weekday FROM training_groups AS g "
                        "JOIN sport_directions AS d ON d.id = g.direction_id "
                        "JOIN schedule_rules AS r ON r.group_id = g.id "
                        "WHERE d.code IN ('BOXING', 'LEGACY_MMA') "
                        "ORDER BY d.code"
                    )
                )
            ).mappings().all()
            seeded_groups = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM training_groups AS g "
                        "JOIN sport_directions AS d ON d.id = g.direction_id "
                        "WHERE g.trainer_id IS NULL AND "
                        "(d.name = 'Кикбоксинг' OR "
                        "(d.name = 'MMA' AND g.name = 'Взрослые'))"
                    )
                )
            ).scalar_one()
            directions = (
                await connection.execute(
                    text(
                        "SELECT code, name FROM sport_directions "
                        "ORDER BY code"
                    )
                )
            ).all()
        assert [
            (group["code"], group["group_name"], group["weekday"])
            for group in groups
        ] == [
            ("BOXING", "Legacy group", SUNDAY),
            ("LEGACY_MMA", "Взрослые", SUNDAY),
        ]
        assert all(group["trainer_id"] is not None for group in groups)
        assert seeded_groups == 0
        assert directions == [("BOXING", "Бокс"), ("LEGACY_MMA", "MMA")]
    finally:
        await engine.dispose()
