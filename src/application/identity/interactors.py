from application.common import Clock, UnitOfWork
from application.identity.commands import RegisterBotUserCommand
from application.identity.dto import RegisterBotUserResult
from application.identity.errors import (
    InvalidBotInviteError,
    RequiredSystemRoleMissingError,
    UserAlreadyRegisteredError,
)
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    BotInviteRepository,
    InviteTokenHasher,
    RoleRepository,
    UserRepository,
)
from domain.identity import Athlete, SystemRoleCode, User

USER_REGISTERED_ACTION = "USER_REGISTERED"
USER_ENTITY_TYPE = "USER"


class RegisterBotUserInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        token_hasher: InviteTokenHasher,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._invites = bot_invite_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work
        self._clock = clock
        self._token_hasher = token_hasher

    async def __call__(
        self,
        command: RegisterBotUserCommand,
    ) -> RegisterBotUserResult:
        async with self._uow:
            now = self._clock.now()
            token_hash = self._token_hasher.hash(command.invite_token)
            invite = await self._invites.get_by_token_hash(token_hash)
            if invite is None or not invite.is_valid(now):
                raise InvalidBotInviteError

            existing_user = await self._users.get_by_telegram_id(
                command.telegram_id
            )
            if existing_user is not None:
                raise UserAlreadyRegisteredError

            role = await self._roles.get_by_code(SystemRoleCode.ATHLETE)
            if role is None or not role.is_system or not role.is_active:
                raise RequiredSystemRoleMissingError

            user_id = await self._users.add(
                User(
                    id=None,
                    telegram_id=command.telegram_id,
                    username=command.username,
                    first_name=command.first_name,
                    last_name=command.last_name or "",
                    is_active=True,
                    registered_at=now,
                    last_seen_at=now,
                )
            )
            await self._roles.assign_to_user(
                user_id=user_id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=now,
            )
            await self._athletes.add(
                Athlete.create_for_registered_user(
                    user_id=user_id,
                    first_name=command.first_name,
                    last_name=command.last_name,
                )
            )
            await self._audit_log.add(
                actor_user_id=user_id,
                action=USER_REGISTERED_ACTION,
                entity_type=USER_ENTITY_TYPE,
                entity_id=user_id,
            )
            await self._uow.commit()

        return RegisterBotUserResult(
            user_id=user_id,
            telegram_id=command.telegram_id,
            role_code=SystemRoleCode.ATHLETE,
            registered_at=now,
        )
