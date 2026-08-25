import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from infrastructure.database.session import create_engine

PROJECT_ROOT = Path(__file__).parents[3]


def test_migration_round_trip_and_models_match_head(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, "9b5a2c7e1d4f")
    athlete_public_id = uuid4()
    asyncio.run(_insert_legacy_athlete(database_url, athlete_public_id))
    command.upgrade(config, "head")
    asyncio.run(_assert_legacy_athlete_preserved(database_url, athlete_public_id))
    command.check(config)
    command.downgrade(config, "9b5a2c7e1d4f")
    command.upgrade(config, "head")
    asyncio.run(_assert_legacy_athlete_preserved(database_url, athlete_public_id))
    command.check(config)


async def _insert_legacy_athlete(
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
                    "VALUES (CAST(:athlete_public_id AS UUID), NULL, :first_name, "
                    ":last_name, NULL, true)"
                ),
                {
                    "athlete_public_id": str(athlete_public_id),
                    "first_name": "Legacy",
                    "last_name": "Athlete",
                },
            )
    finally:
        await engine.dispose()


async def _assert_legacy_athlete_preserved(
    database_url: str,
    athlete_public_id: UUID,
) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT first_name, last_name, birth_date, user_id "
                        "FROM athletes "
                        "WHERE athlete_public_id = "
                        "CAST(:athlete_public_id AS UUID)"
                    ),
                    {"athlete_public_id": str(athlete_public_id)},
                )
            ).one()
        assert row == ("Legacy", "Athlete", None, None)
    finally:
        await engine.dispose()
