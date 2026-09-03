from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from application.trainer_notifications import (
    FindSessionsForTrainerNotificationInteractor,
    NotifyTrainerBeforeSessionCommand,
    NotifyTrainerBeforeSessionInteractor,
    NotifyTrainerOutcome,
    RetryableTrainerNotificationDeliveryError,
    RetryableTrainerNotifierError,
    TrainerNotificationClaim,
    TrainerNotificationClaimOutcome,
    TrainerNotificationMessage,
    TrainerNotificationSession,
)
from domain.club import TrainingGroupType, TrainingSessionStatus

NOW = datetime(2026, 9, 2, 15, 55, tzinfo=UTC)
CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FrozenClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class FakeReader:
    def __init__(
        self,
        session: TrainerNotificationSession | None,
        fresh_session: TrainerNotificationSession | None = None,
    ) -> None:
        self.sessions = [session]
        if fresh_session is not None or session is not None:
            self.sessions.append(fresh_session if fresh_session is not None else session)
        self.get_calls = 0
        self.expected_count = 0
        self.confirmed_count = 0
        self.find_result: tuple[int, ...] = ()
        self.find_args: tuple[datetime, int, datetime] | None = None
        self.expected_args: tuple[int, bool, datetime] | None = None

    async def find_due_session_ids(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[int, ...]:
        self.find_args = (
            reference_now,
            notify_before_seconds,
            stale_pending_before,
        )
        return self.find_result

    async def get_session(
        self,
        training_session_id: int,
    ) -> TrainerNotificationSession | None:
        assert training_session_id == 42
        index = min(self.get_calls, len(self.sessions) - 1)
        self.get_calls += 1
        return self.sessions[index]

    async def count_expected(
        self,
        *,
        training_group_id: int,
        group_is_regular: bool,
        reference_now: datetime,
    ) -> int:
        self.expected_args = (
            training_group_id,
            group_is_regular,
            reference_now,
        )
        return self.expected_count

    async def count_confirmed(self, training_session_id: int) -> int:
        assert training_session_id == 42
        return self.confirmed_count


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.claim_result = TrainerNotificationClaim(
            outcome=TrainerNotificationClaimOutcome.ACQUIRED,
            attempts=1,
            notification_id=100,
        )
        self.claim_calls = 0
        self.sent: tuple[int, str, int, datetime] | None = None
        self.failed_calls: list[tuple[int, str, int]] = []
        self.refreshed: tuple[int, str, int, int, datetime] | None = None
        self.released: tuple[int, str, int] | None = None
        self.released_stale: tuple[str, datetime] | None = None

    async def claim(self, **kwargs: object) -> TrainerNotificationClaim:
        self.claim_calls += 1
        assert kwargs["training_session_id"] == 42
        return self.claim_result

    async def mark_sent(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        attempts: int,
        sent_at: datetime,
    ) -> bool:
        self.sent = (notification_id, idempotency_key, attempts, sent_at)
        return True

    async def mark_failed(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        reference_now: datetime,
    ) -> bool:
        del reference_now
        self.failed_calls.append(
            (notification_id, idempotency_key, expected_attempts)
        )
        return True

    async def refresh_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
        recipient_user_id: int,
        scheduled_at: datetime,
        reference_now: datetime,
    ) -> bool:
        del reference_now
        self.refreshed = (
            notification_id,
            idempotency_key,
            expected_attempts,
            recipient_user_id,
            scheduled_at,
        )
        return True

    async def release_pending(
        self,
        *,
        notification_id: int,
        idempotency_key: str,
        expected_attempts: int,
    ) -> bool:
        self.released = (
            notification_id,
            idempotency_key,
            expected_attempts,
        )
        return True

    async def release_stale_pending(
        self,
        *,
        idempotency_key: str,
        stale_pending_before: datetime,
    ) -> bool:
        self.released_stale = (idempotency_key, stale_pending_before)
        return True


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: tuple[int, TrainerNotificationMessage] | None = None
        self.error: Exception | None = None

    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None:
        if self.error is not None:
            raise self.error
        self.sent = (telegram_id, message)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


def make_session(
    *,
    starts_at: datetime = NOW + timedelta(minutes=5),
    ends_at: datetime = NOW + timedelta(hours=1, minutes=35),
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
    telegram_id: int | None = 900_000_042,
    user_exists: bool = True,
    group_type: TrainingGroupType = TrainingGroupType.REGULAR,
) -> TrainerNotificationSession:
    return TrainerNotificationSession(
        id=42,
        group_id=11,
        trainer_id=7,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        group_type=group_type,
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые #1",
        trainer_user_exists=user_exists,
        trainer_telegram_id=telegram_id,
    )


def build(
    session: TrainerNotificationSession | None,
    fresh_session: TrainerNotificationSession | None = None,
) -> tuple[
    NotifyTrainerBeforeSessionInteractor,
    FakeReader,
    FakeDeliveryRepository,
    FakeNotifier,
    FakeUnitOfWork,
    FrozenClock,
]:
    reader = FakeReader(session, fresh_session)
    deliveries = FakeDeliveryRepository()
    notifier = FakeNotifier()
    uow = FakeUnitOfWork()
    clock = FrozenClock()
    return (
        NotifyTrainerBeforeSessionInteractor(
            reader=reader,
            delivery_repository=deliveries,
            notifier=notifier,
            unit_of_work=uow,
            clock=clock,
            club_timezone=CLUB_TIMEZONE,
        ),
        reader,
        deliveries,
        notifier,
        uow,
        clock,
    )


async def test_poll_uses_one_reference_time_and_ten_minute_stale_window() -> None:
    reader = FakeReader(None)
    reader.find_result = (4, 8)
    clock = FrozenClock()
    interactor = FindSessionsForTrainerNotificationInteractor(reader, clock)

    result = await interactor()

    assert result.training_session_ids == (4, 8)
    assert reader.find_args == (NOW, 300, NOW - timedelta(minutes=10))
    assert clock.calls == 1


async def test_sends_zero_snapshot_using_materialized_session_times() -> None:
    interactor, reader, deliveries, notifier, uow, clock = build(
        make_session()
    )

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is NotifyTrainerOutcome.SENT
    assert notifier.sent is not None
    telegram_id, message = notifier.sent
    assert telegram_id == 900_000_042
    assert message.starts_at == datetime(
        2026, 9, 2, 19, 0, tzinfo=CLUB_TIMEZONE
    )
    assert message.ends_at == datetime(
        2026, 9, 2, 20, 30, tzinfo=CLUB_TIMEZONE
    )
    assert message.expected_count == 0
    assert message.confirmed_count == 0
    assert reader.expected_args == (11, True, NOW)
    assert deliveries.sent == (100, "TRAINER_SESSION_MINUS_5:42", 1, NOW)
    assert uow.commits == 3
    assert clock.calls == 1


async def test_retry_not_due_releases_only_its_pending_attempt() -> None:
    interactor, _, deliveries, notifier, uow, _ = build(
        make_session(starts_at=NOW + timedelta(minutes=20))
    )

    result = await interactor(
        NotifyTrainerBeforeSessionCommand(
            42,
            delivery_attempt=2,
            notification_id=100,
        )
    )

    assert result.outcome is NotifyTrainerOutcome.NOT_DUE
    assert deliveries.released == (100, "TRAINER_SESSION_MINUS_5:42", 1)
    assert notifier.sent is None
    assert uow.commits == 1


async def test_initial_not_due_releases_only_stale_crash_claim() -> None:
    interactor, _, deliveries, notifier, uow, _ = build(
        make_session(starts_at=NOW + timedelta(minutes=20))
    )

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is NotifyTrainerOutcome.NOT_DUE
    assert deliveries.released_stale == (
        "TRAINER_SESSION_MINUS_5:42",
        NOW - timedelta(minutes=10),
    )
    assert notifier.sent is None
    assert uow.commits == 1


@pytest.mark.parametrize(
    ("session", "outcome"),
    [
        (
            make_session(status=TrainingSessionStatus.CANCELLED),
            NotifyTrainerOutcome.CANCELLED,
        ),
        (
            make_session(starts_at=NOW),
            NotifyTrainerOutcome.SESSION_STARTED,
        ),
        (
            make_session(telegram_id=None),
            NotifyTrainerOutcome.TRAINER_UNAVAILABLE,
        ),
    ],
)
async def test_terminal_skip_is_persisted_as_failed(
    session: TrainerNotificationSession,
    outcome: NotifyTrainerOutcome,
) -> None:
    interactor, _, deliveries, notifier, uow, _ = build(session)

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is outcome
    assert deliveries.failed_calls == [
        (100, "TRAINER_SESSION_MINUS_5:42", 1)
    ]
    assert notifier.sent is None
    assert uow.commits == 2


async def test_retryable_error_raises_for_celery_and_keeps_pending() -> None:
    interactor, _, deliveries, notifier, _, _ = build(make_session())
    notifier.error = RetryableTrainerNotifierError()

    with pytest.raises(RetryableTrainerNotificationDeliveryError) as raised:
        await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert raised.value.retry_after_seconds is None
    assert raised.value.notification_id == 100
    assert raised.value.delivery_attempt == 1
    assert deliveries.failed_calls == []


async def test_retry_after_past_start_becomes_terminal_failed() -> None:
    interactor, _, deliveries, notifier, _, _ = build(make_session())
    notifier.error = RetryableTrainerNotifierError(retry_after_seconds=300)

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
    assert deliveries.failed_calls == [
        (100, "TRAINER_SESSION_MINUS_5:42", 1)
    ]


async def test_fresh_pending_skips_counts_and_send() -> None:
    interactor, reader, deliveries, notifier, _, _ = build(make_session())
    deliveries.claim_result = TrainerNotificationClaim(
        outcome=TrainerNotificationClaimOutcome.IN_PROGRESS,
        attempts=1,
        notification_id=100,
    )

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is NotifyTrainerOutcome.IN_PROGRESS
    assert reader.expected_args is None
    assert notifier.sent is None


async def test_post_claim_fresh_group_and_times_drive_counts_and_message() -> None:
    preliminary = make_session()
    fresh = replace(
        preliminary,
        group_id=22,
        starts_at=NOW + timedelta(minutes=4),
        ends_at=NOW + timedelta(hours=2),
        sport_direction_name="Бокс",
        group_name="Старшая группа",
    )
    interactor, reader, deliveries, notifier, _, _ = build(preliminary, fresh)
    reader.expected_count = 6
    reader.confirmed_count = 7

    result = await interactor(NotifyTrainerBeforeSessionCommand(42))

    assert result.outcome is NotifyTrainerOutcome.SENT
    assert reader.get_calls == 2
    assert reader.expected_args == (22, True, NOW)
    assert deliveries.refreshed == (
        100,
        "TRAINER_SESSION_MINUS_5:42",
        1,
        7,
        fresh.starts_at - timedelta(minutes=5),
    )
    assert notifier.sent is not None
    _, message = notifier.sent
    assert message.sport_direction_name == "Бокс"
    assert message.group_name == "Старшая группа"
    assert message.starts_at == fresh.starts_at.astimezone(CLUB_TIMEZONE)
    assert message.ends_at == fresh.ends_at.astimezone(CLUB_TIMEZONE)
    assert message.expected_count == 6
    assert message.confirmed_count == 7
