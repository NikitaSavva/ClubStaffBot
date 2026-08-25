import argparse
import asyncio
import sys

from dishka import AsyncContainer

from application.identity import (
    AssignOwnerCommand,
    AssignOwnerInteractor,
    AssignOwnerResult,
)
from application.identity.errors import (
    OwnerAlreadyAssignedError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from bootstrap.config import Settings
from bootstrap.container import create_container


def positive_telegram_id(raw_value: str) -> int:
    try:
        telegram_id = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "telegram_id must be a positive integer"
        ) from error
    if telegram_id <= 0:
        raise argparse.ArgumentTypeError(
            "telegram_id must be a positive integer"
        )
    return telegram_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assign the single system OWNER role to an existing User.",
    )
    parser.add_argument("telegram_id", type=positive_telegram_id)
    return parser


async def assign_owner(
    container: AsyncContainer,
    telegram_id: int,
) -> AssignOwnerResult:
    async with container() as request_container:
        interactor = await request_container.get(AssignOwnerInteractor)
        return await interactor(AssignOwnerCommand(telegram_id=telegram_id))


async def run(telegram_id: int) -> AssignOwnerResult:
    # BaseSettings loads the required application configuration from environment.
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await assign_owner(container, telegram_id)
    finally:
        await container.close()


def main() -> int:
    telegram_id = build_parser().parse_args().telegram_id
    try:
        result = asyncio.run(run(telegram_id))
    except UserNotFoundError:
        print(
            f"User with telegram_id={telegram_id} does not exist.",
            file=sys.stderr,
        )
        return 2
    except RequiredSystemRoleMissingError:
        print(
            "OWNER system role is missing or inactive. Run system-role "
            "bootstrap first.",
            file=sys.stderr,
        )
        return 3
    except OwnerAlreadyAssignedError:
        print("OWNER is already assigned to another User.", file=sys.stderr)
        return 4

    if result.owner_was_assigned:
        print(f"OWNER role assigned to User {result.target_user_id}.")
    else:
        print("User already has OWNER role.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
