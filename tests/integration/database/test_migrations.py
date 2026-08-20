from pathlib import Path

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).parents[3]


def test_migration_round_trip_and_models_match_head(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, "1e1a708c7c2e")
    command.upgrade(config, "head")
    command.check(config)
