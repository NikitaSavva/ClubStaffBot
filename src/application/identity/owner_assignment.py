from application.common import Clock, UnitOfWork
from application.identity.commands import AssignOwnerCommand
from application.identity.dto import AssignOwnerResult
from application.identity.errors import (
    OwnerAlreadyAssignedError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from application.identity.ports import (
    AuditLogRepository,
    RoleRepository,
    UserRepository,
)
from domain.identity import Role, SystemRoleCode

OWNER_ASSIGNED_ACTION = "OWNER_ASSIGNED"
USER_ENTITY_TYPE = "USER"
OPERATOR_SCRIPT_SOURCE = "OPERATOR_SCRIPT"


class AssignOwnerInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        command: AssignOwnerCommand,
    ) -> AssignOwnerResult:
        async with self._uow:
            target = await self._users.get_by_telegram_id(command.telegram_id)
            if target is None or target.id is None:
                raise UserNotFoundError

            owner_role = _require_owner_role(
                await self._roles.get_by_code_for_update(
                    SystemRoleCode.OWNER
                )
            )
            assigned_user_id = await self._roles.get_assigned_user_id(
                owner_role.id
            )
            if assigned_user_id == target.id:
                return await self._result(
                    target_user_id=target.id,
                    owner_was_assigned=False,
                )
            if assigned_user_id is not None:
                raise OwnerAlreadyAssignedError

            owner_was_assigned = await self._roles.assign_to_user(
                user_id=target.id,
                role_id=owner_role.id,
                assigned_by_user_id=None,
                assigned_at=self._clock.now(),
            )
            if not owner_was_assigned:
                assigned_user_id = await self._roles.get_assigned_user_id(
                    owner_role.id
                )
                if assigned_user_id == target.id:
                    return await self._result(
                        target_user_id=target.id,
                        owner_was_assigned=False,
                    )
                raise OwnerAlreadyAssignedError

            await self._audit_log.add(
                actor_user_id=None,
                action=OWNER_ASSIGNED_ACTION,
                entity_type=USER_ENTITY_TYPE,
                entity_id=target.id,
                payload={
                    "role_code": SystemRoleCode.OWNER.value,
                    "source": OPERATOR_SCRIPT_SOURCE,
                },
            )
            current_role_codes = (
                await self._roles.list_active_codes_for_user(target.id)
            )
            await self._uow.commit()

        return AssignOwnerResult(
            target_user_id=target.id,
            owner_was_assigned=True,
            current_role_codes=current_role_codes,
        )

    async def _result(
        self,
        *,
        target_user_id: int,
        owner_was_assigned: bool,
    ) -> AssignOwnerResult:
        return AssignOwnerResult(
            target_user_id=target_user_id,
            owner_was_assigned=owner_was_assigned,
            current_role_codes=(
                await self._roles.list_active_codes_for_user(target_user_id)
            ),
        )


def _require_owner_role(role: Role | None) -> Role:
    if (
        role is None
        or role.code is not SystemRoleCode.OWNER
        or not role.is_system
        or not role.is_active
    ):
        raise RequiredSystemRoleMissingError
    return role
