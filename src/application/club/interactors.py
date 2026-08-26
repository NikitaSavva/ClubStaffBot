from application.club.commands import AssignTrainingGroupTrainerCommand
from application.club.dto import (
    AssignTrainingGroupTrainerResult,
    TrainingGroupSummary,
)
from application.club.errors import (
    TargetUserIsNotTrainerError,
    TrainingGroupNotFoundError,
    TrainingGroupTrainerAlreadyAssignedError,
)
from application.club.ports import TrainingGroupReader, TrainingGroupRepository
from application.club.queries import (
    ListTrainerCandidatesQuery,
    ListTrainingGroupsQuery,
)
from application.common import UnitOfWork
from application.identity.authorization import require_administrative_actor
from application.identity.dto import BotUserSummary
from application.identity.errors import UserNotFoundError
from application.identity.ports import (
    AuditLogRepository,
    BotUserReader,
    RoleRepository,
    UserRepository,
)
from domain.identity import SystemRoleCode

TRAINER_ASSIGNED_ACTION = "TRAINER_ASSIGNED"
TRAINING_GROUP_ENTITY_TYPE = "TRAINING_GROUP"


class ListTrainingGroupsInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        training_group_reader: TrainingGroupReader,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = training_group_reader

    async def __call__(
        self,
        query: ListTrainingGroupsQuery,
    ) -> tuple[TrainingGroupSummary, ...]:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        return await self._reader.list_all()


class ListTrainerCandidatesInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        bot_user_reader: BotUserReader,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = bot_user_reader

    async def __call__(
        self,
        query: ListTrainerCandidatesQuery,
    ) -> tuple[BotUserSummary, ...]:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        return await self._reader.list_by_role(SystemRoleCode.TRAINER)


class AssignTrainingGroupTrainerInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        training_group_repository: TrainingGroupRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._training_groups = training_group_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work

    async def __call__(
        self,
        command: AssignTrainingGroupTrainerCommand,
    ) -> AssignTrainingGroupTrainerResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            if actor.id is None:
                raise RuntimeError("A persisted User must have an id")

            training_group = await self._training_groups.get_by_id_for_update(
                command.training_group_id
            )
            if training_group is None:
                raise TrainingGroupNotFoundError
            if training_group.trainer_id is not None:
                raise TrainingGroupTrainerAlreadyAssignedError

            trainer = await self._users.get_by_id(command.trainer_user_id)
            if trainer is None or trainer.id is None:
                raise UserNotFoundError
            trainer_role_codes = (
                await self._roles.list_active_codes_for_user(trainer.id)
            )
            if SystemRoleCode.TRAINER not in trainer_role_codes:
                raise TargetUserIsNotTrainerError

            assigned = await self._training_groups.assign_trainer(
                training_group_id=training_group.id,
                trainer_user_id=trainer.id,
            )
            if not assigned:
                raise TrainingGroupTrainerAlreadyAssignedError

            await self._audit_log.add(
                actor_user_id=actor.id,
                action=TRAINER_ASSIGNED_ACTION,
                entity_type=TRAINING_GROUP_ENTITY_TYPE,
                entity_id=training_group.id,
                payload={"trainer_user_id": trainer.id},
            )
            await self._uow.commit()

        return AssignTrainingGroupTrainerResult(
            training_group_id=training_group.id,
            trainer_user_id=trainer.id,
        )
