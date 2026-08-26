import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.training_sessions import (
    GenerateTrainingSessionsCommand,
    GenerateTrainingSessionsInteractor,
    GenerateTrainingSessionsResult,
    MissingTrainingGroupTrainersError,
    TrainingSessionGenerationWindowResolver,
)
from domain.club import TrainingSessionStatus
from infrastructure.database.models import (
    GroupNameModel,
    ScheduleRuleModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingGroupType,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyScheduleRuleRepository,
    SqlAlchemyTrainingSessionRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
MONDAY = date(2026, 8, 24)
SATURDAY = date(2026, 8, 29)
SEEDED_DIRECTION_NAMES = ("Кикбоксинг", "MMA")


@dataclass(frozen=True, slots=True)
class CreatedGroup:
    group_id: int
    direction_id: int
    group_name_id: int
    schedule_rule_ids: tuple[int, ...]
    direction_name: str
    group_name: str


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 26, 11, 40, tzinfo=CLUB_TIMEZONE)


@pytest.fixture
async def session_factory(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def isolated_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await _set_seeded_groups_active(session_factory, active=False)
    try:
        yield session_factory
    finally:
        await _set_seeded_groups_active(session_factory, active=True)


async def _set_seeded_groups_active(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    active: bool,
) -> None:
    async with session_factory.begin() as session:
        group_ids = await _seeded_group_ids(session)
        await session.execute(
            update(TrainingGroupModel)
            .where(TrainingGroupModel.id.in_(group_ids))
            .values(is_active=active)
        )


async def _seeded_group_ids(session: AsyncSession) -> tuple[int, ...]:
    return tuple(
        (
            await session.scalars(
                select(TrainingGroupModel.id)
                .join(
                    SportDirectionModel,
                    SportDirectionModel.id == TrainingGroupModel.direction_id,
                )
                .join(
                    ScheduleRuleModel,
                    ScheduleRuleModel.group_id == TrainingGroupModel.id,
                )
                .where(
                    SportDirectionModel.name.in_(SEEDED_DIRECTION_NAMES),
                    ScheduleRuleModel.weekday != 6,
                )
                .distinct()
            )
        ).all()
    )


async def _add_user(
    session: AsyncSession,
    *,
    first_name: str,
) -> UserModel:
    telegram_id = uuid4().int % 9_000_000_000 + 1_000_000_000
    user = UserModel(
        telegram_id=telegram_id,
        username=None,
        first_name=first_name,
        last_name="Trainer",
        is_active=True,
        registered_at=datetime(2026, 8, 1, tzinfo=CLUB_TIMEZONE),
        last_seen_at=datetime(2026, 8, 1, tzinfo=CLUB_TIMEZONE),
    )
    session.add(user)
    await session.flush()
    return user


async def _add_group(
    session: AsyncSession,
    *,
    trainer_id: int | None,
    weekdays: tuple[int, ...] = (0, 2, 4),
    start_time: time = time(19, 0),
    end_time: time = time(20, 30),
    valid_from: date | None = None,
    valid_until: date | None = None,
    inactive_weekdays: tuple[int, ...] = (),
) -> CreatedGroup:
    token = uuid4().hex
    direction_name = f"Test direction {token}"
    group_name = f"Test group {token}"
    direction = SportDirectionModel(
        code=f"TEST_{token}",
        name=direction_name,
        is_active=True,
    )
    group_name_model = GroupNameModel(name=group_name)
    session.add_all((direction, group_name_model))
    await session.flush()

    group = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=trainer_id,
        name_id=group_name_model.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add(group)
    await session.flush()

    rules = [
        ScheduleRuleModel(
            group_id=group.id,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            valid_from=valid_from,
            valid_until=valid_until,
            is_active=weekday not in inactive_weekdays,
        )
        for weekday in weekdays
    ]
    session.add_all(rules)
    await session.flush()
    return CreatedGroup(
        group_id=group.id,
        direction_id=direction.id,
        group_name_id=group_name_model.id,
        schedule_rule_ids=tuple(rule.id for rule in rules),
        direction_name=direction_name,
        group_name=group_name,
    )


async def _execute_generation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    date_from: date = MONDAY,
    date_to: date = SATURDAY,
) -> GenerateTrainingSessionsResult:
    async with session_factory() as session:
        return await GenerateTrainingSessionsInteractor(
            schedule_rule_repository=SqlAlchemyScheduleRuleRepository(session),
            training_session_repository=(
                SqlAlchemyTrainingSessionRepository(session)
            ),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            club_timezone=CLUB_TIMEZONE,
        )(
            GenerateTrainingSessionsCommand(
                date_from=date_from,
                date_to=date_to,
            )
        )


async def _cleanup_created_data(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    groups: tuple[CreatedGroup, ...],
    user_ids: tuple[int, ...],
) -> None:
    group_ids = tuple(group.group_id for group in groups)
    async with session_factory.begin() as session:
        await session.execute(
            delete(TrainingSessionModel).where(
                TrainingSessionModel.group_id.in_(group_ids)
            )
        )
        await session.execute(
            delete(ScheduleRuleModel).where(
                ScheduleRuleModel.group_id.in_(group_ids)
            )
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id.in_(group_ids)
            )
        )
        await session.execute(
            delete(GroupNameModel).where(
                GroupNameModel.id.in_(
                    tuple(group.group_name_id for group in groups)
                )
            )
        )
        await session.execute(
            delete(SportDirectionModel).where(
                SportDirectionModel.id.in_(
                    tuple(group.direction_id for group in groups)
                )
            )
        )
        await session.execute(
            delete(UserModel).where(UserModel.id.in_(user_ids))
        )


async def test_generation_persists_exact_datetimes_and_trainer_snapshot(
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    groups: tuple[CreatedGroup, ...] = ()
    user_ids: tuple[int, ...] = ()
    try:
        async with isolated_session_factory.begin() as session:
            first_trainer = await _add_user(session, first_name="First")
            second_trainer = await _add_user(session, first_name="Second")
            group = await _add_group(session, trainer_id=first_trainer.id)
            groups = (group,)
            user_ids = (first_trainer.id, second_trainer.id)

        result = await _execute_generation(isolated_session_factory)

        async with isolated_session_factory.begin() as session:
            await session.execute(
                update(TrainingGroupModel)
                .where(TrainingGroupModel.id == group.group_id)
                .values(trainer_id=second_trainer.id)
            )

        async with isolated_session_factory() as session:
            generated = (
                await session.scalars(
                    select(TrainingSessionModel)
                    .where(TrainingSessionModel.group_id == group.group_id)
                    .order_by(TrainingSessionModel.starts_at)
                )
            ).all()

        assert result.created_count == 3
        assert result.skipped_count == 0
        assert [
            item.starts_at.astimezone(CLUB_TIMEZONE) for item in generated
        ] == [
            datetime(2026, 8, 24, 19, 0, tzinfo=CLUB_TIMEZONE),
            datetime(2026, 8, 26, 19, 0, tzinfo=CLUB_TIMEZONE),
            datetime(2026, 8, 28, 19, 0, tzinfo=CLUB_TIMEZONE),
        ]
        assert [
            item.ends_at.astimezone(CLUB_TIMEZONE) for item in generated
        ] == [
            datetime(2026, 8, 24, 20, 30, tzinfo=CLUB_TIMEZONE),
            datetime(2026, 8, 26, 20, 30, tzinfo=CLUB_TIMEZONE),
            datetime(2026, 8, 28, 20, 30, tzinfo=CLUB_TIMEZONE),
        ]
        assert {item.trainer_id for item in generated} == {first_trainer.id}
        assert all(
            item.status is TrainingSessionStatus.SCHEDULED
            for item in generated
        )
        assert all(not item.is_overridden for item in generated)
    finally:
        if groups and user_ids:
            await _cleanup_created_data(
                isolated_session_factory,
                groups=groups,
                user_ids=user_ids,
            )


async def test_missing_trainer_rolls_back_all_generation_and_lists_group(
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    groups: tuple[CreatedGroup, ...] = ()
    user_ids: tuple[int, ...] = ()
    try:
        async with isolated_session_factory.begin() as session:
            trainer = await _add_user(session, first_name="Assigned")
            assigned_group = await _add_group(session, trainer_id=trainer.id)
            missing_group = await _add_group(
                session,
                trainer_id=None,
                weekdays=(1, 3, 5),
                start_time=time(17, 30),
                end_time=time(18, 45),
            )
            groups = (assigned_group, missing_group)
            user_ids = (trainer.id,)

        with pytest.raises(MissingTrainingGroupTrainersError) as error:
            await _execute_generation(isolated_session_factory)

        async with isolated_session_factory() as session:
            persisted_count = await session.scalar(
                select(func.count())
                .select_from(TrainingSessionModel)
                .where(
                    TrainingSessionModel.group_id.in_(
                        tuple(group.group_id for group in groups)
                    )
                )
            )

        assert persisted_count == 0
        assert len(error.value.training_groups) == 1
        problem = error.value.training_groups[0]
        assert problem.training_group_id == missing_group.group_id
        assert problem.direction_name == missing_group.direction_name
        assert problem.group_name == missing_group.group_name
        assert [rule.weekday for rule in problem.schedule] == [1, 3, 5]
    finally:
        if groups and user_ids:
            await _cleanup_created_data(
                isolated_session_factory,
                groups=groups,
                user_ids=user_ids,
            )


async def test_partially_generated_week_is_completed_without_overwrite(
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    groups: tuple[CreatedGroup, ...] = ()
    user_ids: tuple[int, ...] = ()
    try:
        async with isolated_session_factory.begin() as session:
            default_trainer = await _add_user(session, first_name="Default")
            replacement_trainer = await _add_user(
                session,
                first_name="Replacement",
            )
            group = await _add_group(session, trainer_id=default_trainer.id)
            groups = (group,)
            user_ids = (default_trainer.id, replacement_trainer.id)
            session.add(
                TrainingSessionModel(
                    schedule_rule_id=group.schedule_rule_ids[0],
                    group_id=group.group_id,
                    trainer_id=replacement_trainer.id,
                    starts_at=datetime(
                        2026,
                        8,
                        24,
                        19,
                        0,
                        tzinfo=CLUB_TIMEZONE,
                    ),
                    ends_at=datetime(
                        2026,
                        8,
                        24,
                        20,
                        30,
                        tzinfo=CLUB_TIMEZONE,
                    ),
                    status=TrainingSessionStatus.SCHEDULED,
                    is_overridden=True,
                )
            )

        result = await _execute_generation(isolated_session_factory)

        async with isolated_session_factory() as session:
            generated = (
                await session.scalars(
                    select(TrainingSessionModel)
                    .where(TrainingSessionModel.group_id == group.group_id)
                    .order_by(TrainingSessionModel.starts_at)
                )
            ).all()

        assert result.created_count == 2
        assert result.skipped_count == 1
        assert len(generated) == 3
        assert generated[0].trainer_id == replacement_trainer.id
        assert generated[0].is_overridden
        assert {item.trainer_id for item in generated[1:]} == {
            default_trainer.id
        }
    finally:
        if groups and user_ids:
            await _cleanup_created_data(
                isolated_session_factory,
                groups=groups,
                user_ids=user_ids,
            )


async def test_rule_lifecycle_inactive_and_sunday_are_respected(
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    groups: tuple[CreatedGroup, ...] = ()
    user_ids: tuple[int, ...] = ()
    try:
        async with isolated_session_factory.begin() as session:
            trainer = await _add_user(session, first_name="Lifecycle")
            active_group = await _add_group(
                session,
                trainer_id=trainer.id,
                weekdays=(0, 2, 4, 6),
                valid_from=date(2026, 8, 26),
                valid_until=date(2026, 8, 28),
                inactive_weekdays=(2,),
            )
            groups = (active_group,)
            user_ids = (trainer.id,)

        result = await _execute_generation(
            isolated_session_factory,
            date_to=date(2026, 8, 30),
        )

        async with isolated_session_factory() as session:
            generated_dates = (
                await session.scalars(
                    select(TrainingSessionModel.starts_at)
                    .where(
                        TrainingSessionModel.group_id == active_group.group_id
                    )
                )
            ).all()

        assert result.created_count == 1
        assert [
            item.astimezone(CLUB_TIMEZONE).date() for item in generated_dates
        ] == [date(2026, 8, 28)]
    finally:
        if groups and user_ids:
            await _cleanup_created_data(
                isolated_session_factory,
                groups=groups,
                user_ids=user_ids,
            )


async def test_concurrent_generation_keeps_one_row_per_occurrence(
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    groups: tuple[CreatedGroup, ...] = ()
    user_ids: tuple[int, ...] = ()
    try:
        async with isolated_session_factory.begin() as session:
            trainer = await _add_user(session, first_name="Concurrent")
            group = await _add_group(session, trainer_id=trainer.id)
            groups = (group,)
            user_ids = (trainer.id,)

        results = await asyncio.gather(
            _execute_generation(isolated_session_factory),
            _execute_generation(isolated_session_factory),
        )

        async with isolated_session_factory() as session:
            persisted_count = await session.scalar(
                select(func.count())
                .select_from(TrainingSessionModel)
                .where(TrainingSessionModel.group_id == group.group_id)
            )

        assert sum(result.created_count for result in results) == 3
        assert sum(result.skipped_count for result in results) == 3
        assert persisted_count == 3
    finally:
        if groups and user_ids:
            await _cleanup_created_data(
                isolated_session_factory,
                groups=groups,
                user_ids=user_ids,
            )


async def test_seeded_schedule_materializes_full_current_week_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    trainer_id: int | None = None
    group_ids: tuple[int, ...] = ()
    try:
        async with session_factory.begin() as session:
            trainer = await _add_user(session, first_name="Seeded")
            trainer_id = trainer.id
            group_ids = await _seeded_group_ids(session)
            assert len(group_ids) == 10
            await session.execute(
                update(TrainingGroupModel)
                .where(TrainingGroupModel.id.in_(group_ids))
                .values(trainer_id=trainer.id)
            )

        resolver = TrainingSessionGenerationWindowResolver(
            FrozenClock(),
            CLUB_TIMEZONE,
        )
        window = resolver.bootstrap_window()
        first_result = await _execute_generation(
            session_factory,
            date_from=window.date_from,
            date_to=window.date_to,
        )
        second_result = await _execute_generation(
            session_factory,
            date_from=window.date_from,
            date_to=window.date_to,
        )

        async with session_factory() as session:
            starts_at = (
                await session.scalars(
                    select(TrainingSessionModel.starts_at)
                    .where(TrainingSessionModel.group_id.in_(group_ids))
                    .order_by(TrainingSessionModel.starts_at)
                )
            ).all()

        local_starts_at = [
            item.astimezone(CLUB_TIMEZONE) for item in starts_at
        ]
        assert first_result.created_count == 32
        assert first_result.skipped_count == 0
        assert second_result.created_count == 0
        assert second_result.skipped_count == 32
        assert len(local_starts_at) == 32
        assert {item.date().weekday() for item in local_starts_at} == {
            0,
            1,
            2,
            3,
            4,
            5,
        }
        assert any(item.date() == MONDAY for item in local_starts_at)
        assert any(item.date() == date(2026, 8, 25) for item in local_starts_at)
        assert any(
            item.date() == date(2026, 8, 26) and item.time() < time(11, 40)
            for item in local_starts_at
        )
        assert any(
            item.date() == date(2026, 8, 26) and item.time() > time(11, 40)
            for item in local_starts_at
        )
        assert any(item.date() == SATURDAY for item in local_starts_at)
        assert not any(item.date().weekday() == 6 for item in local_starts_at)
    finally:
        if group_ids:
            async with session_factory.begin() as session:
                await session.execute(
                    delete(TrainingSessionModel).where(
                        TrainingSessionModel.group_id.in_(group_ids)
                    )
                )
                await session.execute(
                    update(TrainingGroupModel)
                    .where(TrainingGroupModel.id.in_(group_ids))
                    .values(trainer_id=None)
                )
                if trainer_id is not None:
                    await session.execute(
                        delete(UserModel).where(UserModel.id == trainer_id)
                    )
