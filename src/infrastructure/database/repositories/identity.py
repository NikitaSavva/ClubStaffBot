from datetime import datetime

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from application.identity.errors import UserAlreadyRegisteredError
from domain.identity import Athlete, BotInvite, Role, SystemRoleCode, User
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    BotInviteModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)


class SqlAlchemyAthleteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, athlete: Athlete) -> int:
        model = AthleteModel(
            athlete_public_id=athlete.athlete_public_id,
            user_id=athlete.user_id,
            first_name=athlete.first_name,
            last_name=athlete.last_name,
            birth_date=athlete.birth_date,
            phone=athlete.phone,
            is_active=athlete.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        return model.id

    async def get_by_id_for_update(
        self,
        athlete_id: int,
    ) -> Athlete | None:
        model = await self._session.scalar(
            select(AthleteModel)
            .where(AthleteModel.id == athlete_id)
            .with_for_update()
        )
        return _to_athlete(model)

    async def list_unlinked(self) -> tuple[Athlete, ...]:
        models = await self._session.scalars(
            select(AthleteModel)
            .where(AthleteModel.user_id.is_(None))
            .order_by(
                AthleteModel.last_name.asc().nulls_last(),
                AthleteModel.first_name.asc(),
                AthleteModel.id.asc(),
            )
        )
        return tuple(_to_required_athlete(model) for model in models)

    async def link_to_user(self, *, athlete_id: int, user_id: int) -> bool:
        linked_athlete_id = await self._session.scalar(
            update(AthleteModel)
            .where(
                AthleteModel.id == athlete_id,
                AthleteModel.user_id.is_(None),
            )
            .values(user_id=user_id)
            .returning(AthleteModel.id)
        )
        return linked_athlete_id is not None


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        model = await self._session.scalar(
            select(UserModel).where(UserModel.telegram_id == telegram_id)
        )
        return _to_user(model)

    async def get_by_id(self, user_id: int) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_user(model)

    async def get_by_id_for_update(self, user_id: int) -> User | None:
        model = await self._session.scalar(
            select(UserModel)
            .where(UserModel.id == user_id)
            .with_for_update()
        )
        return _to_user(model)

    async def add(self, user: User) -> int:
        model = UserModel(
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            registered_at=user.registered_at,
            last_seen_at=user.last_seen_at,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise UserAlreadyRegisteredError from error
            raise
        return model.id


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, code: SystemRoleCode) -> Role | None:
        model = await self._session.scalar(
            select(RoleModel).where(RoleModel.code == code.value)
        )
        if model is None:
            return None
        return Role(
            id=model.id,
            code=SystemRoleCode(model.code),
            is_system=model.is_system,
            is_active=model.is_active,
        )

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        codes = await self._session.scalars(
            select(RoleModel.code)
            .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
            .where(
                UserRoleModel.user_id == user_id,
                RoleModel.is_system.is_(True),
                RoleModel.is_active.is_(True),
                RoleModel.code.in_(
                    tuple(code.value for code in SystemRoleCode)
                ),
            )
        )
        assigned_codes = {SystemRoleCode(code) for code in codes}
        return tuple(
            code for code in SystemRoleCode if code in assigned_codes
        )

    async def is_assigned(self, *, user_id: int, role_id: int) -> bool:
        is_assigned = await self._session.scalar(
            select(
                exists().where(
                    UserRoleModel.user_id == user_id,
                    UserRoleModel.role_id == role_id,
                )
            )
        )
        return bool(is_assigned)

    async def assign_to_user(
        self,
        *,
        user_id: int,
        role_id: int,
        assigned_by_user_id: int | None,
        assigned_at: datetime,
    ) -> bool:
        assigned_user_role_id = await self._session.scalar(
            insert(UserRoleModel)
            .values(
                user_id=user_id,
                role_id=role_id,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=assigned_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserRoleModel.user_id,
                    UserRoleModel.role_id,
                ]
            )
            .returning(UserRoleModel.id)
        )
        return assigned_user_role_id is not None

    async def remove_from_user(
        self,
        *,
        user_id: int,
        role_id: int,
    ) -> bool:
        removed_user_role_id = await self._session.scalar(
            delete(UserRoleModel)
            .where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.role_id == role_id,
            )
            .returning(UserRoleModel.id)
        )
        return removed_user_role_id is not None


class SqlAlchemyBotInviteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> BotInvite | None:
        model = await self._session.scalar(
            select(BotInviteModel).where(
                BotInviteModel.token_hash == token_hash
            )
        )
        return _to_bot_invite(model)

    async def get_by_token_hash_for_update(
        self,
        token_hash: str,
    ) -> BotInvite | None:
        model = await self._session.scalar(
            select(BotInviteModel)
            .where(BotInviteModel.token_hash == token_hash)
            .with_for_update()
        )
        return _to_bot_invite(model)

    async def add(self, invite: BotInvite) -> int:
        model = BotInviteModel(
            token_hash=invite.token_hash,
            purpose=invite.purpose,
            athlete_id=invite.athlete_id,
            is_active=invite.is_active,
            expires_at=invite.expires_at,
            revoked_at=invite.revoked_at,
            consumed_at=invite.consumed_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model.id

    async def consume(self, *, invite_id: int, consumed_at: datetime) -> bool:
        consumed_invite_id = await self._session.scalar(
            update(BotInviteModel)
            .where(
                BotInviteModel.id == invite_id,
                BotInviteModel.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
            .returning(BotInviteModel.id)
        )
        return consumed_invite_id is not None


class SqlAlchemyAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._session.add(
            AuditLogModel(
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )
        )


def _to_user(model: UserModel | None) -> User | None:
    if model is None:
        return None
    return User(
        id=model.id,
        telegram_id=model.telegram_id,
        username=model.username,
        first_name=model.first_name,
        last_name=model.last_name,
        is_active=model.is_active,
        registered_at=model.registered_at,
        last_seen_at=model.last_seen_at,
    )


def _to_athlete(model: AthleteModel | None) -> Athlete | None:
    if model is None:
        return None
    return _to_required_athlete(model)


def _to_required_athlete(model: AthleteModel) -> Athlete:
    return Athlete(
        id=model.id,
        athlete_public_id=model.athlete_public_id,
        user_id=model.user_id,
        first_name=model.first_name,
        last_name=model.last_name,
        birth_date=model.birth_date,
        phone=model.phone,
        is_active=model.is_active,
    )


def _to_bot_invite(model: BotInviteModel | None) -> BotInvite | None:
    if model is None:
        return None
    return BotInvite(
        id=model.id,
        token_hash=model.token_hash,
        purpose=model.purpose,
        athlete_id=model.athlete_id,
        is_active=model.is_active,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        consumed_at=model.consumed_at,
    )
