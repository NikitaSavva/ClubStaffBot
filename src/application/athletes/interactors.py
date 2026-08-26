from application.athletes.commands import CreateManualAthleteCommand
from application.athletes.dto import AthleteSummary, CreateManualAthleteResult
from application.athletes.ports import AthleteReader
from application.athletes.queries import ListAthletesQuery
from application.common import UnitOfWork
from application.identity.authorization import require_administrative_actor
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    RoleRepository,
    UserRepository,
)
from domain.identity import Athlete

ATHLETE_CREATED_MANUALLY_ACTION = "ATHLETE_CREATED_MANUALLY"
ATHLETE_ENTITY_TYPE = "ATHLETE"


class ListAthletesInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        athlete_reader: AthleteReader,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = athlete_reader

    async def __call__(
        self,
        query: ListAthletesQuery,
    ) -> tuple[AthleteSummary, ...]:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        return await self._reader.list_all()


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
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )

            athlete = Athlete.create_manually(
                first_name=command.first_name,
                last_name=command.last_name,
                birth_date=command.birth_date,
            )
            if athlete.birth_date is None or athlete.last_name is None:
                raise RuntimeError(
                    "A manually created Athlete must be complete"
                )
            result = CreateManualAthleteResult(
                first_name=athlete.first_name,
                last_name=athlete.last_name,
                birth_date=athlete.birth_date,
            )
            athlete_id = await self._athletes.add(athlete)
            await self._audit_log.add(
                actor_user_id=actor.id,
                action=ATHLETE_CREATED_MANUALLY_ACTION,
                entity_type=ATHLETE_ENTITY_TYPE,
                entity_id=athlete_id,
            )
            await self._uow.commit()

        return result
