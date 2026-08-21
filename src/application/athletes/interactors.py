from application.athletes.commands import CreateManualAthleteCommand
from application.athletes.dto import CreateManualAthleteResult
from application.common import UnitOfWork
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    RoleRepository,
    UserRepository,
)
from domain.identity import Athlete, SystemRoleCode

ATHLETE_CREATED_MANUALLY_ACTION = "ATHLETE_CREATED_MANUALLY"
ATHLETE_ENTITY_TYPE = "ATHLETE"


class CreateManualAthleteInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work

    async def __call__(
        self,
        command: CreateManualAthleteCommand,
    ) -> CreateManualAthleteResult:
        async with self._uow:
            actor = await self._users.get_by_telegram_id(
                command.actor_telegram_id
            )
            if actor is None or actor.id is None:
                raise UserNotFoundError

            role_codes = await self._roles.list_active_codes_for_user(actor.id)
            if SystemRoleCode.ADMINISTRATOR not in role_codes:
                raise AdministratorPermissionRequiredError

            athlete = Athlete.create_manually(first_name=command.first_name)
            athlete_id = await self._athletes.add(athlete)
            await self._audit_log.add(
                actor_user_id=actor.id,
                action=ATHLETE_CREATED_MANUALLY_ACTION,
                entity_type=ATHLETE_ENTITY_TYPE,
                entity_id=athlete_id,
            )
            await self._uow.commit()

        return CreateManualAthleteResult(first_name=athlete.first_name)
