from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.training_sessions import CurrentWeekScheduleFilters
from domain.club import TrainingGroupType, TrainingSessionStatus
from infrastructure.database.models import (
    GroupNameModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.readers import (
    SqlAlchemyCurrentWeekScheduleReader,
)
from infrastructure.database.session import create_engine, create_session_factory

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
WEEK_START_LOCAL = datetime(2026, 8, 24, tzinfo=CLUB_TIMEZONE)
WEEK_END_LOCAL = datetime(2026, 8, 30, tzinfo=CLUB_TIMEZONE)
WEEK_START = WEEK_START_LOCAL.astimezone(UTC)
WEEK_END = WEEK_END_LOCAL.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ScheduleContext:
    regular_a_id: int
    regular_b_id: int
    mini_id: int
    current_trainer_id: int
    other_trainer_id: int
    monday_session_id: int
    cancelled_session_id: int
    current_trainer_session_id: int


@asynccontextmanager
async def arranged_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ScheduleContext]:
    suffix = uuid4().hex[:10]
    user_ids: list[int] = []
    group_ids: list[int] = []
    name_ids: list[int] = []
    direction_id: int | None = None
    async with session_factory.begin() as session:
        current_trainer = _user(suffix, "current", 1)
        other_trainer = _user(suffix, "other", 2)
        session.add_all((current_trainer, other_trainer))
        await session.flush()
        user_ids.extend((current_trainer.id, other_trainer.id))

        direction = SportDirectionModel(
            code=f"SCHEDULE_{suffix}",
            name=f"Кикбоксинг {suffix}",
            short_name=None,
            is_active=True,
        )
        session.add(direction)
        await session.flush()
        direction_id = direction.id

        names = tuple(
            GroupNameModel(name=f"{label} {suffix}")
            for label in ("Взрослые A", "Взрослые B", "Мини")
        )
        session.add_all(names)
        await session.flush()
        name_ids.extend(item.id for item in names)

        regular_a = _group(
            direction.id,
            names[0].id,
            other_trainer.id,
            TrainingGroupType.REGULAR,
        )
        regular_b = _group(
            direction.id,
            names[1].id,
            other_trainer.id,
            TrainingGroupType.REGULAR,
        )
        mini = _group(
            direction.id,
            names[2].id,
            other_trainer.id,
            TrainingGroupType.MINI,
        )
        session.add_all((regular_a, regular_b, mini))
        await session.flush()
        group_ids.extend((regular_a.id, regular_b.id, mini.id))

        previous_sunday = _session(
            regular_a.id,
            other_trainer.id,
            WEEK_START_LOCAL - timedelta(minutes=1),
        )
        monday = _session(
            regular_a.id,
            other_trainer.id,
            WEEK_START_LOCAL,
        )
        cancelled = _session(
            regular_a.id,
            other_trainer.id,
            WEEK_START_LOCAL + timedelta(hours=9),
            status=TrainingSessionStatus.CANCELLED,
        )
        same_time_later_id = _session(
            regular_b.id,
            other_trainer.id,
            WEEK_START_LOCAL + timedelta(hours=9),
        )
        trainer_snapshot = _session(
            regular_a.id,
            current_trainer.id,
            WEEK_START_LOCAL + timedelta(days=2, hours=19),
        )
        mini_session = _session(
            mini.id,
            other_trainer.id,
            WEEK_START_LOCAL + timedelta(days=4, hours=14),
        )
        saturday = _session(
            regular_b.id,
            other_trainer.id,
            WEEK_START_LOCAL + timedelta(days=5, hours=23),
        )
        sunday = _session(
            regular_b.id,
            other_trainer.id,
            WEEK_END_LOCAL,
        )
        session.add_all(
            (
                previous_sunday,
                monday,
                cancelled,
                same_time_later_id,
                trainer_snapshot,
                mini_session,
                saturday,
                sunday,
            )
        )
        await session.flush()
        context = ScheduleContext(
            regular_a_id=regular_a.id,
            regular_b_id=regular_b.id,
            mini_id=mini.id,
            current_trainer_id=current_trainer.id,
            other_trainer_id=other_trainer.id,
            monday_session_id=monday.id,
            cancelled_session_id=cancelled.id,
            current_trainer_session_id=trainer_snapshot.id,
        )

    try:
        yield context
    finally:
        async with session_factory.begin() as cleanup:
            await cleanup.execute(
                delete(TrainingSessionModel).where(
                    TrainingSessionModel.group_id.in_(group_ids)
                )
            )
            await cleanup.execute(
                delete(TrainingGroupModel).where(
                    TrainingGroupModel.id.in_(group_ids)
                )
            )
            await cleanup.execute(
                delete(GroupNameModel).where(GroupNameModel.id.in_(name_ids))
            )
            if direction_id is not None:
                await cleanup.execute(
                    delete(SportDirectionModel).where(
                        SportDirectionModel.id == direction_id
                    )
                )
            await cleanup.execute(
                delete(UserModel).where(UserModel.id.in_(user_ids))
            )


def _user(suffix: str, label: str, offset: int) -> UserModel:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    return UserModel(
        telegram_id=8_800_000_000 + int(suffix[:6], 16) + offset,
        username=f"schedule_{label}_{suffix}",
        first_name=label,
        last_name="Trainer",
        is_active=True,
        registered_at=now,
        last_seen_at=now,
    )


def _group(
    direction_id: int,
    name_id: int,
    trainer_id: int,
    group_type: TrainingGroupType,
) -> TrainingGroupModel:
    return TrainingGroupModel(
        direction_id=direction_id,
        trainer_id=trainer_id,
        name_id=name_id,
        group_type=group_type,
        is_active=True,
    )


def _session(
    group_id: int,
    trainer_id: int,
    starts_at: datetime,
    *,
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
) -> TrainingSessionModel:
    return TrainingSessionModel(
        schedule_rule_id=None,
        group_id=group_id,
        trainer_id=trainer_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        status=status,
        is_overridden=False,
    )


async def test_reader_uses_half_open_week_and_one_ordered_query(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(" ".join(statement.lower().split()))

    try:
        async with arranged_schedule(session_factory) as context:
            event.listen(
                engine.sync_engine,
                "before_cursor_execute",
                record_statement,
            )
            async with session_factory() as session:
                result = await SqlAlchemyCurrentWeekScheduleReader(
                    session
                ).list(
                    CurrentWeekScheduleFilters(
                        week_start=WEEK_START,
                        week_end=WEEK_END,
                    )
                )
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                record_statement,
            )

            assert len(statements) == 1
            assert "schedule_rules" not in statements[0]
            assert "join training_groups" in statements[0]
            ids = [item.id for item in result]
            assert context.monday_session_id == ids[0]
            assert context.cancelled_session_id in ids
            assert [item.starts_at for item in result] == sorted(
                item.starts_at for item in result
            )
            tied = [
                item.id
                for item in result
                if item.starts_at
                == (WEEK_START_LOCAL + timedelta(hours=9)).astimezone(UTC)
            ]
            assert tied == sorted(tied)
            assert all(WEEK_START <= item.starts_at < WEEK_END for item in result)
    finally:
        await engine.dispose()


async def test_reader_applies_group_and_regular_filters(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with arranged_schedule(session_factory) as context:
            async with session_factory() as session:
                reader = SqlAlchemyCurrentWeekScheduleReader(session)
                specific = await reader.list(
                    CurrentWeekScheduleFilters(
                        week_start=WEEK_START,
                        week_end=WEEK_END,
                        training_group_id=context.regular_a_id,
                    )
                )
                regular = await reader.list(
                    CurrentWeekScheduleFilters(
                        week_start=WEEK_START,
                        week_end=WEEK_END,
                        group_type=TrainingGroupType.REGULAR,
                    )
                )
                all_sessions = await reader.list(
                    CurrentWeekScheduleFilters(
                        week_start=WEEK_START,
                        week_end=WEEK_END,
                    )
                )

            assert {item.training_group_id for item in specific} == {
                context.regular_a_id
            }
            assert context.mini_id not in {
                item.training_group_id for item in regular
            }
            assert context.mini_id in {
                item.training_group_id for item in all_sessions
            }
    finally:
        await engine.dispose()


async def test_trainer_filter_uses_session_snapshot_not_group_trainer(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with arranged_schedule(session_factory) as context:
            async with session_factory() as session:
                result = await SqlAlchemyCurrentWeekScheduleReader(
                    session
                ).list(
                    CurrentWeekScheduleFilters(
                        week_start=WEEK_START,
                        week_end=WEEK_END,
                        trainer_id=context.current_trainer_id,
                    )
                )

            assert [item.id for item in result] == [
                context.current_trainer_session_id
            ]
            assert result[0].training_group_id == context.regular_a_id
            assert context.current_trainer_id != context.other_trainer_id
    finally:
        await engine.dispose()
