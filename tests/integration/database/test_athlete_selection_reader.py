from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from application.athletes import AthleteSearch, AthleteSearchKind
from infrastructure.database.models import AthleteModel, UserModel
from infrastructure.database.readers import SqlAlchemyAthleteSelectionReader

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def test_list_and_surname_search_include_athletes_without_users(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    user = UserModel(
        telegram_id=80_000_000 + uuid4().int % 1_000_000_000,
        username=f"linked_{suffix}",
        first_name="Linked",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add(user)
    await db_session.flush()
    linked = AthleteModel(
        user_id=user.id,
        first_name="Борис",
        last_name=f"Selector{suffix}",
        birth_date=None,
        phone=None,
        is_active=True,
    )
    manual = AthleteModel(
        user_id=None,
        first_name="Анна",
        last_name=f"Selector{suffix}",
        birth_date=date(2000, 5, 4),
        phone=None,
        is_active=True,
    )
    db_session.add_all([linked, manual])
    await db_session.flush()
    reader = SqlAlchemyAthleteSelectionReader(db_session)

    result = await reader.list_page(
        offset=0,
        limit=10,
        search=AthleteSearch(
            AthleteSearchKind.SURNAME,
            f"sElEcToR{suffix}",
        ),
    )

    assert [item.athlete_id for item in result] == [manual.id, linked.id]
    assert result[0].birth_date == date(2000, 5, 4)
    assert await reader.get_by_id(manual.id) == result[0]


async def test_username_search_is_case_insensitive_exact(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    username = f"Exact_{suffix}"
    user = UserModel(
        telegram_id=80_000_000 + uuid4().int % 1_000_000_000,
        username=username,
        first_name="Linked",
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add(user)
    await db_session.flush()
    linked = AthleteModel(
        user_id=user.id,
        first_name="Иван",
        last_name="Иванов",
        birth_date=None,
        phone=None,
        is_active=True,
    )
    manual = AthleteModel(
        user_id=None,
        first_name="Пётр",
        last_name="Петров",
        birth_date=None,
        phone=None,
        is_active=True,
    )
    db_session.add_all([linked, manual])
    await db_session.flush()
    reader = SqlAlchemyAthleteSelectionReader(db_session)

    exact = await reader.list_page(
        offset=0,
        limit=10,
        search=AthleteSearch(
            AthleteSearchKind.TELEGRAM_USERNAME,
            username.swapcase(),
        ),
    )
    partial = await reader.list_page(
        offset=0,
        limit=10,
        search=AthleteSearch(
            AthleteSearchKind.TELEGRAM_USERNAME,
            username[:-1],
        ),
    )

    assert [item.athlete_id for item in exact] == [linked.id]
    assert partial == ()
    assert manual.id not in {item.athlete_id for item in exact}


async def test_surname_wildcards_are_escaped_and_pagination_is_stable(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:8]
    athletes = [
        AthleteModel(
            user_id=None,
            first_name=f"Имя {index:02}",
            last_name=f"Literal%_{suffix}",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        for index in range(10)
    ]
    wildcard_decoy = AthleteModel(
        user_id=None,
        first_name="Decoy",
        last_name=f"LiteralXX{suffix}",
        birth_date=None,
        phone=None,
        is_active=True,
    )
    db_session.add_all([*athletes, wildcard_decoy])
    await db_session.flush()
    reader = SqlAlchemyAthleteSelectionReader(db_session)
    search = AthleteSearch(
        AthleteSearchKind.SURNAME,
        f"%_{suffix}",
    )

    first = await reader.list_page(offset=0, limit=9, search=search)
    second = await reader.list_page(offset=8, limit=9, search=search)

    assert [item.athlete_id for item in first[:8]] == [
        athlete.id for athlete in athletes[:8]
    ]
    assert [item.athlete_id for item in second] == [
        athlete.id for athlete in athletes[8:]
    ]
    assert wildcard_decoy.id not in {item.athlete_id for item in first + second}
