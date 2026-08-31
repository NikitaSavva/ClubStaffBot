from collections.abc import Iterable

from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthletePermissionRequiredError,
    TrainerPermissionRequiredError,
    UserNotFoundError,
)
from application.identity.ports import RoleRepository, UserRepository
from domain.identity import SystemRoleCode, User

_ADMINISTRATIVE_ROLE_CODES = frozenset(
    {
        SystemRoleCode.ADMINISTRATOR,
        SystemRoleCode.OWNER,
    }
)


def can_administrate(role_codes: Iterable[SystemRoleCode]) -> bool:
    return not _ADMINISTRATIVE_ROLE_CODES.isdisjoint(role_codes)


async def require_administrative_actor(
    *,
    telegram_id: int,
    users: UserRepository,
    roles: RoleRepository,
    required_role: SystemRoleCode | None = None,
) -> User:
    actor = await users.get_by_telegram_id(telegram_id)
    if actor is None or actor.id is None:
        raise UserNotFoundError

    role_codes = await roles.list_active_codes_for_user(actor.id)
    if required_role is not None and required_role not in (
        SystemRoleCode.ADMINISTRATOR,
        SystemRoleCode.OWNER,
    ):
        raise ValueError("required_role must be administrative")
    if (
        required_role not in role_codes
        if required_role is not None
        else not can_administrate(role_codes)
    ):
        raise AdministratorPermissionRequiredError
    return actor


async def require_athlete_actor(
    *,
    telegram_id: int,
    users: UserRepository,
    roles: RoleRepository,
) -> User:
    actor = await users.get_by_telegram_id(telegram_id)
    if actor is None or actor.id is None:
        raise UserNotFoundError

    role_codes = await roles.list_active_codes_for_user(actor.id)
    if SystemRoleCode.ATHLETE not in role_codes:
        raise AthletePermissionRequiredError
    return actor


async def require_trainer_actor(
    *,
    telegram_id: int,
    users: UserRepository,
    roles: RoleRepository,
) -> User:
    actor = await users.get_by_telegram_id(telegram_id)
    if actor is None or actor.id is None:
        raise UserNotFoundError

    role_codes = await roles.list_active_codes_for_user(actor.id)
    if SystemRoleCode.TRAINER not in role_codes:
        raise TrainerPermissionRequiredError
    return actor
