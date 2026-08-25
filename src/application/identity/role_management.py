from application.common import Clock, UnitOfWork
from application.identity.authorization import require_administrative_actor
from application.identity.commands import (
    AssignUserRoleCommand,
    RemoveUserRoleCommand,
)
from application.identity.dto import (
    AssignUserRoleResult,
    BotUserSummary,
    RemoveUserRoleResult,
    SearchBotUsersResult,
)
from application.identity.errors import (
    LastUserRoleRemovalForbiddenError,
    OwnerRoleManagementForbiddenError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from application.identity.ports import (
    AuditLogRepository,
    BotUserReader,
    RoleRepository,
    UserRepository,
)
from application.identity.queries import SearchBotUsersQuery
from domain.identity import Role, SystemRoleCode, User

ROLE_ASSIGNED_ACTION = "ROLE_ASSIGNED"
ROLE_REMOVED_ACTION = "ROLE_REMOVED"
USER_ENTITY_TYPE = "USER"


def _require_active_system_role(role: Role | None) -> Role:
    if role is None or not role.is_system or not role.is_active:
        raise RequiredSystemRoleMissingError
    return role


class SearchBotUsersInteractor:
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
        query: SearchBotUsersQuery,
    ) -> SearchBotUsersResult:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        search_term = query.query.strip().removeprefix("@").strip()
        users = await self._reader.search(search_term)
        return SearchBotUsersResult(
            users=users,
            assignable_role_codes=tuple(
                code
                for code in SystemRoleCode
                if code is not SystemRoleCode.OWNER
            ),
        )


class AssignUserRoleInteractor:
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
        command: AssignUserRoleCommand,
    ) -> AssignUserRoleResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            actor_user_id = _persisted_user_id(actor)

            if command.role_code is SystemRoleCode.OWNER:
                raise OwnerRoleManagementForbiddenError

            target = await self._users.get_by_id(command.target_user_id)
            if target is None or target.id is None:
                raise UserNotFoundError

            role = _require_active_system_role(
                await self._roles.get_by_code(command.role_code)
            )
            if await self._roles.is_assigned(
                user_id=target.id,
                role_id=role.id,
            ):
                return await self._already_assigned_result(
                    target_user_id=target.id,
                    role_code=role.code,
                )

            role_was_assigned = await self._roles.assign_to_user(
                user_id=target.id,
                role_id=role.id,
                assigned_by_user_id=actor_user_id,
                assigned_at=self._clock.now(),
            )
            if not role_was_assigned:
                return await self._already_assigned_result(
                    target_user_id=target.id,
                    role_code=role.code,
                )

            await self._audit_log.add(
                actor_user_id=actor_user_id,
                action=ROLE_ASSIGNED_ACTION,
                entity_type=USER_ENTITY_TYPE,
                entity_id=target.id,
                payload={"role_code": role.code.value},
            )
            current_role_codes = await self._roles.list_active_codes_for_user(
                target.id
            )
            await self._uow.commit()

        return AssignUserRoleResult(
            target_user_id=target.id,
            role_code=role.code,
            role_was_assigned=True,
            current_role_codes=current_role_codes,
        )

    async def _already_assigned_result(
        self,
        *,
        target_user_id: int,
        role_code: SystemRoleCode,
    ) -> AssignUserRoleResult:
        current_role_codes = await self._roles.list_active_codes_for_user(
            target_user_id
        )
        return AssignUserRoleResult(
            target_user_id=target_user_id,
            role_code=role_code,
            role_was_assigned=False,
            current_role_codes=current_role_codes,
        )


class RemoveUserRoleInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work

    async def __call__(
        self,
        command: RemoveUserRoleCommand,
    ) -> RemoveUserRoleResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            actor_user_id = _persisted_user_id(actor)

            if command.role_code is SystemRoleCode.OWNER:
                raise OwnerRoleManagementForbiddenError

            target = await self._users.get_by_id_for_update(
                command.target_user_id
            )
            if target is None or target.id is None:
                raise UserNotFoundError

            role = _require_active_system_role(
                await self._roles.get_by_code(command.role_code)
            )
            current_role_codes = (
                await self._roles.list_active_codes_for_user(target.id)
            )
            if role.code not in current_role_codes:
                return _remove_user_role_result(
                    target=target,
                    role_code=role.code,
                    role_was_removed=False,
                    current_role_codes=current_role_codes,
                )
            if len(current_role_codes) == 1:
                raise LastUserRoleRemovalForbiddenError

            role_was_removed = await self._roles.remove_from_user(
                user_id=target.id,
                role_id=role.id,
            )
            if not role_was_removed:
                return _remove_user_role_result(
                    target=target,
                    role_code=role.code,
                    role_was_removed=False,
                    current_role_codes=(
                        await self._roles.list_active_codes_for_user(target.id)
                    ),
                )

            await self._audit_log.add(
                actor_user_id=actor_user_id,
                action=ROLE_REMOVED_ACTION,
                entity_type=USER_ENTITY_TYPE,
                entity_id=target.id,
                payload={"role_code": role.code.value},
            )
            current_role_codes = (
                await self._roles.list_active_codes_for_user(target.id)
            )
            await self._uow.commit()

        return _remove_user_role_result(
            target=target,
            role_code=role.code,
            role_was_removed=True,
            current_role_codes=current_role_codes,
        )


def _remove_user_role_result(
    *,
    target: User,
    role_code: SystemRoleCode,
    role_was_removed: bool,
    current_role_codes: tuple[SystemRoleCode, ...],
) -> RemoveUserRoleResult:
    target_user_id = _persisted_user_id(target)
    return RemoveUserRoleResult(
        target_user_id=target_user_id,
        role_code=role_code,
        role_was_removed=role_was_removed,
        current_role_codes=current_role_codes,
        target_user=BotUserSummary(
            user_id=target_user_id,
            first_name=target.first_name,
            last_name=target.last_name,
            username=target.username,
            role_codes=current_role_codes,
        ),
    )


def _persisted_user_id(user: User) -> int:
    if user.id is None:
        raise RuntimeError("A persisted User must have an id")
    return user.id
