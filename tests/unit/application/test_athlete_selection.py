from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from application.athletes import (
    ATHLETE_SELECTION_PAGE_SIZE,
    AthleteSearch,
    AthleteSearchKind,
    AthleteSelectionItem,
    GetAthleteSelectionInteractor,
    GetAthleteSelectionQuery,
    ListAthleteSelectionInteractor,
    ListAthleteSelectionQuery,
)
from application.identity.errors import AdministratorPermissionRequiredError
from domain.identity import SystemRoleCode, User

TELEGRAM_ID = 123456
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


class FakeUsers:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        if telegram_id != TELEGRAM_ID:
            return None
        return User(
            id=7,
            telegram_id=telegram_id,
            username="admin",
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )


class FakeRoles:
    def __init__(self, codes: tuple[SystemRoleCode, ...]) -> None:
        self.codes = codes

    async def list_active_codes_for_user(
        self,
        user_id: int,
    ) -> tuple[SystemRoleCode, ...]:
        assert user_id == 7
        return self.codes


class FakeReader:
    def __init__(self) -> None:
        self.items = tuple(_item(index) for index in range(1, 12))
        self.list_calls: list[tuple[int, int, AthleteSearch | None]] = []
        self.get_calls: list[int] = []

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        search: AthleteSearch | None,
    ) -> tuple[AthleteSelectionItem, ...]:
        self.list_calls.append((offset, limit, search))
        return self.items[offset : offset + limit]

    async def get_by_id(
        self,
        athlete_id: int,
    ) -> AthleteSelectionItem | None:
        self.get_calls.append(athlete_id)
        return next(
            (item for item in self.items if item.athlete_id == athlete_id),
            None,
        )


def _item(index: int) -> AthleteSelectionItem:
    return AthleteSelectionItem(
        athlete_id=index,
        athlete_public_id=UUID(int=index),
        first_name=f"Имя {index}",
        last_name=f"Фамилия {index}",
        birth_date=date(2000, 1, min(index, 28)),
    )


async def test_list_uses_one_extra_row_for_page_flags() -> None:
    reader = FakeReader()
    search = AthleteSearch(AthleteSearchKind.SURNAME, "Иванов")
    interactor = ListAthleteSelectionInteractor(
        FakeUsers(),
        FakeRoles((SystemRoleCode.ADMINISTRATOR,)),
        reader,
    )

    result = await interactor(
        ListAthleteSelectionQuery(
            actor_telegram_id=TELEGRAM_ID,
            page=0,
            search=search,
        )
    )

    assert len(result.items) == ATHLETE_SELECTION_PAGE_SIZE
    assert result.has_previous is False
    assert result.has_next is True
    assert reader.list_calls == [(0, ATHLETE_SELECTION_PAGE_SIZE + 1, search)]


async def test_second_page_uses_sql_offset_and_has_previous() -> None:
    reader = FakeReader()
    search = AthleteSearch(AthleteSearchKind.SURNAME, "Фамилия")
    interactor = ListAthleteSelectionInteractor(
        FakeUsers(),
        FakeRoles((SystemRoleCode.OWNER,)),
        reader,
    )

    result = await interactor(
        ListAthleteSelectionQuery(
            actor_telegram_id=TELEGRAM_ID,
            page=1,
            search=search,
        )
    )

    assert [item.athlete_id for item in result.items] == [9, 10, 11]
    assert result.has_previous is True
    assert result.has_next is False
    assert reader.list_calls == [(8, 9, search)]


async def test_get_selected_athlete_reloads_by_id() -> None:
    reader = FakeReader()
    interactor = GetAthleteSelectionInteractor(
        FakeUsers(),
        FakeRoles((SystemRoleCode.ADMINISTRATOR,)),
        reader,
    )

    result = await interactor(
        GetAthleteSelectionQuery(
            actor_telegram_id=TELEGRAM_ID,
            athlete_id=5,
        )
    )

    assert result == reader.items[4]
    assert reader.get_calls == [5]


async def test_selector_requires_administrative_role() -> None:
    reader = FakeReader()
    interactor = ListAthleteSelectionInteractor(
        FakeUsers(),
        FakeRoles((SystemRoleCode.ATHLETE,)),
        reader,
    )

    with pytest.raises(AdministratorPermissionRequiredError):
        await interactor(
            ListAthleteSelectionQuery(actor_telegram_id=TELEGRAM_ID)
        )

    assert reader.list_calls == []
