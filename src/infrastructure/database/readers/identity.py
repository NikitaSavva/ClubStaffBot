from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.athletes import (
    AthleteSearch,
    AthleteSearchKind,
    AthleteSelectionItem,
)
from application.identity.dto import BotUserSummary
from domain.identity import SystemRoleCode
from infrastructure.database.models import (
    AthleteModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)


class SqlAlchemyAthleteSelectionReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        search: AthleteSearch | None,
    ) -> tuple[AthleteSelectionItem, ...]:
        statement = _athlete_selection_statement()
        if search is not None:
            if search.kind is AthleteSearchKind.SURNAME:
                statement = statement.where(
                    AthleteModel.last_name.ilike(
                        _contains_pattern(search.value),
                        escape="\\",
                    )
                )
            else:
                statement = statement.join(
                    UserModel,
                    UserModel.id == AthleteModel.user_id,
                ).where(
                    UserModel.username.ilike(
                        _escape_like_pattern(search.value),
                        escape="\\",
                    )
                )
        rows = (
            await self._session.execute(
                statement.offset(offset).limit(limit)
            )
        ).all()
        return tuple(_athlete_selection_item(row) for row in rows)

    async def get_by_id(
        self,
        athlete_id: int,
    ) -> AthleteSelectionItem | None:
        row = (
            await self._session.execute(
                _athlete_selection_statement().where(
                    AthleteModel.id == athlete_id
                )
            )
        ).one_or_none()
        return _athlete_selection_item(row) if row is not None else None


def _athlete_selection_statement() -> Any:
    return select(
        AthleteModel.id,
        AthleteModel.athlete_public_id,
        AthleteModel.first_name,
        AthleteModel.last_name,
        AthleteModel.birth_date,
    ).order_by(
        AthleteModel.last_name.asc().nulls_last(),
        AthleteModel.first_name.asc(),
        AthleteModel.id.asc(),
    )


def _athlete_selection_item(row: Any) -> AthleteSelectionItem:
    return AthleteSelectionItem(
        athlete_id=row.id,
        athlete_public_id=row.athlete_public_id,
        first_name=row.first_name,
        last_name=row.last_name,
        birth_date=row.birth_date,
    )


@dataclass(slots=True)
class _UserRow:
    user_id: int
    first_name: str
    last_name: str
    username: str | None
    role_codes: set[SystemRoleCode]


class SqlAlchemyBotUserReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, query: str) -> tuple[BotUserSummary, ...]:
        statement = _user_summary_statement()
        if query:
            pattern = _contains_pattern(query)
            statement = statement.where(
                or_(
                    UserModel.first_name.ilike(pattern, escape="\\"),
                    UserModel.last_name.ilike(pattern, escape="\\"),
                    UserModel.username.ilike(pattern, escape="\\"),
                    func.concat_ws(
                        " ",
                        UserModel.first_name,
                        UserModel.last_name,
                    ).ilike(pattern, escape="\\"),
                )
            )

        return _build_summaries(
            (await self._session.execute(statement)).all()
        )

    async def list_by_role(
        self,
        role_code: SystemRoleCode,
    ) -> tuple[BotUserSummary, ...]:
        users_with_role = (
            select(UserRoleModel.user_id)
            .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
            .where(
                RoleModel.code == role_code.value,
                RoleModel.is_system.is_(True),
                RoleModel.is_active.is_(True),
            )
        )
        statement = _user_summary_statement().where(
            UserModel.id.in_(users_with_role)
        )
        return _build_summaries(
            (await self._session.execute(statement)).all()
        )


def _user_summary_statement() -> Any:
    return (
        select(
            UserModel.id,
            UserModel.first_name,
            UserModel.last_name,
            UserModel.username,
            RoleModel.code,
        )
        .select_from(UserModel)
        .outerjoin(
            UserRoleModel,
            UserRoleModel.user_id == UserModel.id,
        )
        .outerjoin(
            RoleModel,
            and_(
                RoleModel.id == UserRoleModel.role_id,
                RoleModel.is_system.is_(True),
                RoleModel.is_active.is_(True),
                RoleModel.code.in_(
                    tuple(code.value for code in SystemRoleCode)
                ),
            ),
        )
        .order_by(
            UserModel.last_name.asc(),
            UserModel.first_name.asc(),
            UserModel.id.asc(),
        )
    )


def _build_summaries(rows: Any) -> tuple[BotUserSummary, ...]:
    users: dict[int, _UserRow] = {}
    for user_id, first_name, last_name, username, role_code in rows:
        user = users.setdefault(
            user_id,
            _UserRow(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                username=username,
                role_codes=set(),
            ),
        )
        if role_code is not None:
            user.role_codes.add(SystemRoleCode(role_code))

    return tuple(
        BotUserSummary(
            user_id=user.user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            role_codes=tuple(
                code
                for code in SystemRoleCode
                if code in user.role_codes
            ),
        )
        for user in users.values()
    )


def _contains_pattern(query: str) -> str:
    return f"%{_escape_like_pattern(query)}%"


def _escape_like_pattern(query: str) -> str:
    return (
        query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
