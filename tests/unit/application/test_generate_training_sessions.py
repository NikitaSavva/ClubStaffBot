from datetime import date, datetime, time
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from application.training_sessions import (
    GenerateTrainingSessionsCommand,
    GenerateTrainingSessionsInteractor,
    InvalidGenerationWindowError,
    MissingTrainingGroupTrainersError,
    NewTrainingSession,
    ScheduleRuleForGeneration,
)
from domain.club import TrainingSessionStatus

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
MONDAY = date(2026, 8, 24)
SATURDAY = date(2026, 8, 29)
TRAINER_ID = 101


class FakeScheduleRuleRepository:
    def __init__(self, rules: tuple[ScheduleRuleForGeneration, ...]) -> None:
        self.rules = rules
        self.requested_window: tuple[date, date] | None = None

    async def list_for_generation(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> tuple[ScheduleRuleForGeneration, ...]:
        self.requested_window = (date_from, date_to)
        return self.rules


class FakeTrainingSessionRepository:
    def __init__(
        self,
        existing: tuple[NewTrainingSession, ...] = (),
    ) -> None:
        self.persisted = {
            (session.schedule_rule_id, session.starts_at): session
            for session in existing
        }
        self.add_calls = 0

    async def add_missing(
        self,
        training_sessions: tuple[NewTrainingSession, ...],
    ) -> int:
        self.add_calls += 1
        created_count = 0
        for training_session in training_sessions:
            key = (
                training_session.schedule_rule_id,
                training_session.starts_at,
            )
            if key not in self.persisted:
                self.persisted[key] = training_session
                created_count += 1
        return created_count


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.committed = False

    async def __aenter__(self) -> Self:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.exited = True

    async def commit(self) -> None:
        self.committed = True


def schedule_rule(
    *,
    schedule_rule_id: int,
    weekday: int,
    trainer_id: int | None = TRAINER_ID,
    training_group_id: int = 11,
    direction_name: str = "Кикбоксинг",
    group_name: str = "Взрослые",
    start_time: time = time(19, 0),
    end_time: time = time(20, 30),
    valid_from: date | None = None,
    valid_until: date | None = None,
    is_active: bool = True,
) -> ScheduleRuleForGeneration:
    return ScheduleRuleForGeneration(
        schedule_rule_id=schedule_rule_id,
        training_group_id=training_group_id,
        trainer_id=trainer_id,
        direction_name=direction_name,
        group_name=group_name,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=is_active,
    )


def build_interactor(
    rules: tuple[ScheduleRuleForGeneration, ...],
    *,
    sessions: FakeTrainingSessionRepository | None = None,
) -> tuple[
    GenerateTrainingSessionsInteractor,
    FakeScheduleRuleRepository,
    FakeTrainingSessionRepository,
    FakeUnitOfWork,
]:
    rules_repository = FakeScheduleRuleRepository(rules)
    sessions_repository = sessions or FakeTrainingSessionRepository()
    uow = FakeUnitOfWork()
    return (
        GenerateTrainingSessionsInteractor(
            schedule_rule_repository=rules_repository,
            training_session_repository=sessions_repository,
            unit_of_work=uow,
            club_timezone=CLUB_TIMEZONE,
        ),
        rules_repository,
        sessions_repository,
        uow,
    )


async def test_generates_mon_wed_fri_with_exact_aware_datetimes() -> None:
    interactor, rules, sessions, uow = build_interactor(
        (
            schedule_rule(schedule_rule_id=1, weekday=0),
            schedule_rule(schedule_rule_id=2, weekday=2),
            schedule_rule(schedule_rule_id=3, weekday=4),
        )
    )

    result = await interactor(
        GenerateTrainingSessionsCommand(MONDAY, SATURDAY)
    )

    generated = tuple(sessions.persisted.values())
    assert rules.requested_window == (MONDAY, SATURDAY)
    assert result.created_count == 3
    assert result.skipped_count == 0
    assert [session.starts_at for session in generated] == [
        datetime(2026, 8, 24, 19, 0, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 26, 19, 0, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 28, 19, 0, tzinfo=CLUB_TIMEZONE),
    ]
    assert [session.ends_at for session in generated] == [
        datetime(2026, 8, 24, 20, 30, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 26, 20, 30, tzinfo=CLUB_TIMEZONE),
        datetime(2026, 8, 28, 20, 30, tzinfo=CLUB_TIMEZONE),
    ]
    assert all(session.training_group_id == 11 for session in generated)
    assert all(session.trainer_id == TRAINER_ID for session in generated)
    assert all(
        session.status is TrainingSessionStatus.SCHEDULED
        for session in generated
    )
    assert all(not session.is_overridden for session in generated)
    assert uow.committed


async def test_missing_trainer_aborts_entire_window_before_insert() -> None:
    interactor, _, sessions, uow = build_interactor(
        (
            schedule_rule(schedule_rule_id=1, weekday=0),
            schedule_rule(
                schedule_rule_id=2,
                weekday=1,
                trainer_id=None,
                training_group_id=22,
                group_name="Дети 6–9 лет",
                start_time=time(17, 30),
                end_time=time(18, 45),
            ),
            schedule_rule(
                schedule_rule_id=3,
                weekday=3,
                trainer_id=None,
                training_group_id=22,
                group_name="Дети 6–9 лет",
                start_time=time(17, 30),
                end_time=time(18, 45),
            ),
        )
    )

    with pytest.raises(MissingTrainingGroupTrainersError) as error:
        await interactor(GenerateTrainingSessionsCommand(MONDAY, SATURDAY))

    assert sessions.add_calls == 0
    assert sessions.persisted == {}
    assert not uow.committed
    assert uow.exited
    assert len(error.value.training_groups) == 1
    problem = error.value.training_groups[0]
    assert problem.training_group_id == 22
    assert problem.direction_name == "Кикбоксинг"
    assert problem.group_name == "Дети 6–9 лет"
    assert [rule.weekday for rule in problem.schedule] == [1, 3]


@pytest.mark.parametrize(
    ("valid_from", "valid_until", "expected_dates"),
    [
        (
            date(2026, 8, 26),
            None,
            [date(2026, 8, 26), date(2026, 8, 28)],
        ),
        (
            None,
            date(2026, 8, 26),
            [date(2026, 8, 24), date(2026, 8, 26)],
        ),
    ],
)
async def test_applies_rule_lifecycle_per_occurrence_date(
    valid_from: date | None,
    valid_until: date | None,
    expected_dates: list[date],
) -> None:
    interactor, _, sessions, _ = build_interactor(
        tuple(
            schedule_rule(
                schedule_rule_id=index + 1,
                weekday=weekday,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            for index, weekday in enumerate((0, 2, 4))
        )
    )

    await interactor(GenerateTrainingSessionsCommand(MONDAY, SATURDAY))

    assert [
        session.starts_at.date() for session in sessions.persisted.values()
    ] == expected_dates


async def test_inactive_and_sunday_rules_do_not_generate_sessions() -> None:
    interactor, _, sessions, uow = build_interactor(
        (
            schedule_rule(
                schedule_rule_id=1,
                weekday=0,
                is_active=False,
            ),
            schedule_rule(schedule_rule_id=2, weekday=6),
        )
    )

    result = await interactor(
        GenerateTrainingSessionsCommand(MONDAY, date(2026, 8, 30))
    )

    assert result.created_count == 0
    assert result.skipped_count == 0
    assert sessions.persisted == {}
    assert uow.committed


async def test_repeated_generation_is_idempotent_and_preserves_snapshot() -> None:
    rules = FakeScheduleRuleRepository(
        (
            schedule_rule(schedule_rule_id=1, weekday=0),
            schedule_rule(schedule_rule_id=2, weekday=2),
            schedule_rule(schedule_rule_id=3, weekday=4),
        )
    )
    sessions = FakeTrainingSessionRepository()

    first_uow = FakeUnitOfWork()
    first = GenerateTrainingSessionsInteractor(
        rules,
        sessions,
        first_uow,
        CLUB_TIMEZONE,
    )
    first_result = await first(
        GenerateTrainingSessionsCommand(MONDAY, SATURDAY)
    )

    rules.rules = tuple(
        schedule_rule(
            schedule_rule_id=index + 1,
            weekday=weekday,
            trainer_id=202,
        )
        for index, weekday in enumerate((0, 2, 4))
    )
    second_uow = FakeUnitOfWork()
    second = GenerateTrainingSessionsInteractor(
        rules,
        sessions,
        second_uow,
        CLUB_TIMEZONE,
    )
    second_result = await second(
        GenerateTrainingSessionsCommand(MONDAY, SATURDAY)
    )

    assert first_result.created_count == 3
    assert second_result.created_count == 0
    assert second_result.skipped_count == 3
    assert len(sessions.persisted) == 3
    assert {
        session.trainer_id for session in sessions.persisted.values()
    } == {TRAINER_ID}


async def test_partially_generated_week_adds_only_missing_occurrences() -> None:
    existing = NewTrainingSession(
        schedule_rule_id=1,
        training_group_id=11,
        trainer_id=TRAINER_ID,
        starts_at=datetime(2026, 8, 24, 19, 0, tzinfo=CLUB_TIMEZONE),
        ends_at=datetime(2026, 8, 24, 20, 30, tzinfo=CLUB_TIMEZONE),
        status=TrainingSessionStatus.SCHEDULED,
        is_overridden=False,
    )
    session_repository = FakeTrainingSessionRepository((existing,))
    interactor, _, sessions, _ = build_interactor(
        (
            schedule_rule(schedule_rule_id=1, weekday=0),
            schedule_rule(schedule_rule_id=2, weekday=2),
            schedule_rule(schedule_rule_id=3, weekday=4),
        ),
        sessions=session_repository,
    )

    result = await interactor(
        GenerateTrainingSessionsCommand(MONDAY, SATURDAY)
    )

    assert result.created_count == 2
    assert result.skipped_count == 1
    assert len(sessions.persisted) == 3
    assert sessions.persisted[(1, existing.starts_at)] is existing


async def test_invalid_generation_window_is_rejected_before_uow() -> None:
    interactor, _, sessions, uow = build_interactor(())

    with pytest.raises(InvalidGenerationWindowError):
        await interactor(
            GenerateTrainingSessionsCommand(SATURDAY, MONDAY)
        )

    assert not uow.entered
    assert sessions.add_calls == 0
