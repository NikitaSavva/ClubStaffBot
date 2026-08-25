from application.common import Clock, UnitOfWork
from application.identity.authorization import require_administrative_actor
from application.identity.commands import (
    CreateAthleteAccountLinkInviteCommand,
    LinkAthleteAccountCommand,
)
from application.identity.dto import (
    CreateAthleteAccountLinkInviteResult,
    LinkAthleteAccountResult,
    UnlinkedAthlete,
)
from application.identity.errors import (
    AthleteAlreadyLinkedError,
    AthleteNotFoundError,
    InvalidBotInviteError,
    RequiredSystemRoleMissingError,
    UserAlreadyRegisteredError,
)
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    BotInviteRepository,
    InviteTokenGenerator,
    InviteTokenHasher,
    RoleRepository,
    UserRepository,
)
from application.identity.queries import ListUnlinkedAthletesQuery
from domain.identity import (
    BotInvite,
    BotInvitePurpose,
    Role,
    SystemRoleCode,
    User,
)

ATHLETE_ACCOUNT_LINK_INVITE_CREATED_ACTION = (
    "ATHLETE_ACCOUNT_LINK_INVITE_CREATED"
)
ATHLETE_ACCOUNT_LINKED_ACTION = "ATHLETE_ACCOUNT_LINKED"
ATHLETE_ENTITY_TYPE = "ATHLETE"
BOT_INVITE_ENTITY_TYPE = "BOT_INVITE"


def _require_active_athlete_role(role: Role | None) -> Role:
    if role is None or not role.is_system or not role.is_active:
        raise RequiredSystemRoleMissingError
    return role


class ListUnlinkedAthletesInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository

    async def __call__(
        self,
        query: ListUnlinkedAthletesQuery,
    ) -> tuple[UnlinkedAthlete, ...]:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        athletes = await self._athletes.list_unlinked()
        return tuple(
            UnlinkedAthlete(
                athlete_id=_persisted_athlete_id(athlete.id),
                first_name=athlete.first_name,
                last_name=athlete.last_name,
                birth_date=athlete.birth_date,
            )
            for athlete in athletes
        )


class CreateAthleteAccountLinkInviteInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        bot_invite_repository: BotInviteRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        token_generator: InviteTokenGenerator,
        token_hasher: InviteTokenHasher,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._invites = bot_invite_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work
        self._token_generator = token_generator
        self._token_hasher = token_hasher

    async def __call__(
        self,
        command: CreateAthleteAccountLinkInviteCommand,
    ) -> CreateAthleteAccountLinkInviteResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            actor_user_id = _persisted_user_id(actor.id)

            athlete = await self._athletes.get_by_id_for_update(
                command.athlete_id
            )
            if athlete is None:
                raise AthleteNotFoundError
            if athlete.user_id is not None:
                raise AthleteAlreadyLinkedError

            raw_token = self._token_generator.generate()
            invite_id = await self._invites.add(
                BotInvite(
                    id=None,
                    token_hash=self._token_hasher.hash(raw_token),
                    purpose=BotInvitePurpose.ATHLETE_LINK,
                    athlete_id=command.athlete_id,
                    is_active=True,
                    expires_at=None,
                    revoked_at=None,
                    consumed_at=None,
                )
            )
            await self._audit_log.add(
                actor_user_id=actor_user_id,
                action=ATHLETE_ACCOUNT_LINK_INVITE_CREATED_ACTION,
                entity_type=BOT_INVITE_ENTITY_TYPE,
                entity_id=invite_id,
            )
            await self._uow.commit()

        return CreateAthleteAccountLinkInviteResult(
            invite_id=invite_id,
            athlete_id=command.athlete_id,
            raw_token=raw_token,
        )


class LinkAthleteAccountInteractor:
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
        command: LinkAthleteAccountCommand,
    ) -> LinkAthleteAccountResult:
        async with self._uow:
            now = self._clock.now()
            token_hash = self._token_hasher.hash(command.invite_token)
            invite = await self._invites.get_by_token_hash_for_update(
                token_hash
            )
            if (
                invite is None
                or not invite.is_valid(now)
                or invite.purpose is not BotInvitePurpose.ATHLETE_LINK
                or invite.athlete_id is None
                or invite.id is None
            ):
                raise InvalidBotInviteError

            existing_user = await self._users.get_by_telegram_id(
                command.telegram_id
            )
            if existing_user is not None:
                raise UserAlreadyRegisteredError

            role = _require_active_athlete_role(
                await self._roles.get_by_code(SystemRoleCode.ATHLETE)
            )
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

            athlete_id = invite.athlete_id
            athlete = await self._athletes.get_by_id_for_update(athlete_id)
            if athlete is None:
                raise AthleteNotFoundError
            if athlete.user_id is not None:
                raise AthleteAlreadyLinkedError
            if not await self._athletes.link_to_user(
                athlete_id=athlete_id,
                user_id=user_id,
            ):
                raise AthleteAlreadyLinkedError

            if not await self._invites.consume(
                invite_id=invite.id,
                consumed_at=now,
            ):
                raise InvalidBotInviteError
            await self._audit_log.add(
                actor_user_id=user_id,
                action=ATHLETE_ACCOUNT_LINKED_ACTION,
                entity_type=ATHLETE_ENTITY_TYPE,
                entity_id=athlete_id,
            )
            await self._uow.commit()

        return LinkAthleteAccountResult(
            user_id=user_id,
            athlete_id=athlete_id,
            telegram_id=command.telegram_id,
            role_code=SystemRoleCode.ATHLETE,
            linked_at=now,
        )


def _persisted_athlete_id(athlete_id: int | None) -> int:
    if athlete_id is None:
        raise RuntimeError("A persisted Athlete must have an id")
    return athlete_id


def _persisted_user_id(user_id: int | None) -> int:
    if user_id is None:
        raise RuntimeError("A persisted User must have an id")
    return user_id
