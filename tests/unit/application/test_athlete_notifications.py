from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from zoneinfo import ZoneInfo

import pytest

from application.athlete_notifications import (
    AthleteNotificationCandidate,
    AthleteNotificationMessage,
    AthleteNotificationRecipient,
    AthleteNotificationSession,
    FindAthletesForSessionReminderInteractor,
    NotifyAthleteBeforeSessionCommand,
    NotifyAthleteBeforeSessionInteractor,
    NotifyAthleteOutcome,
    RetryableAthleteNotificationDeliveryError,
)
from application.notification_delivery import (
    NotificationClaim,
    NotificationClaimOutcome,
    RetryableNotificationSenderError,
)
from domain.club import TrainingSessionStatus

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
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
        session: AthleteNotificationSession | None,
        *,
        fresh_session: AthleteNotificationSession | None = None,
        recipient: AthleteNotificationRecipient | None = None,
        fresh_recipient: AthleteNotificationRecipient | None = None,
    ) -> None:
        self.sessions = [session, fresh_session if fresh_session is not None else session]
        initial_recipient = recipient or AthleteNotificationRecipient(9, 7, 900_007)
        self.recipients = [
            initial_recipient,
            fresh_recipient if fresh_recipient is not None else initial_recipient,
        ]
        self.session_calls = 0
        self.recipient_calls = 0
        self.find_result: tuple[AthleteNotificationCandidate, ...] = ()
        self.find_args: tuple[datetime, int, int, datetime] | None = None

    async def find_due_candidates(
        self,
        *,
        reference_now: datetime,
        notify_before_seconds: int,
        grace_window_seconds: int,
        stale_pending_before: datetime,
    ) -> tuple[AthleteNotificationCandidate, ...]:
        self.find_args = (
            reference_now,
            notify_before_seconds,
            grace_window_seconds,
            stale_pending_before,
        )
        return self.find_result

    async def get_session(
        self,
        training_session_id: int,
    ) -> AthleteNotificationSession | None:
        assert training_session_id == 42
        index = min(self.session_calls, 1)
        self.session_calls += 1
        return self.sessions[index]

    async def get_eligible_recipient(
        self,
        *,
        athlete_id: int,
        training_group_id: int,
        reference_now: datetime,
    ) -> AthleteNotificationRecipient | None:
        assert athlete_id == 9
        assert training_group_id in {11, 12}
        assert reference_now == NOW
        index = min(self.recipient_calls, 1)
        self.recipient_calls += 1
        return self.recipients[index]


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.claim_result = NotificationClaim(
            NotificationClaimOutcome.ACQUIRED,
            attempts=1,
            notification_id=100,
        )
        self.claim_args: dict[str, object] | None = None
        self.sent = False
        self.failed = False
        self.released = False
        self.refreshed: tuple[int, datetime] | None = None

    async def claim(self, **kwargs: object) -> NotificationClaim:
        self.claim_args = kwargs
        return self.claim_result

    async def mark_sent(self, **kwargs: object) -> bool:
        self.sent = True
        return True

    async def mark_failed(self, **kwargs: object) -> bool:
        self.failed = True
        return True

    async def refresh_pending(self, **kwargs: object) -> bool:
        self.refreshed = (
            int(kwargs["recipient_user_id"]),
            kwargs["scheduled_at"],  # type: ignore[arg-type]
        )
        return True

    async def release_pending(self, **kwargs: object) -> bool:
        self.released = True
        return True

    async def release_stale_pending(self, **kwargs: object) -> bool:
        self.released = True
        return True


class FakeNotifier:
    def __init__(self) -> None:
        self.call: tuple[int, AthleteNotificationMessage] | None = None
        self.error: Exception | None = None

    async def send(
        self,
        *,
        telegram_id: int,
        message: AthleteNotificationMessage,
    ) -> None:
        if self.error is not None:
            raise self.error
        self.call = (telegram_id, message)


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
    starts_at: datetime = NOW + timedelta(hours=2),
    ends_at: datetime = NOW + timedelta(hours=3, minutes=30),
    status: TrainingSessionStatus = TrainingSessionStatus.SCHEDULED,
    group_id: int = 11,
) -> AthleteNotificationSession:
    return AthleteNotificationSession(
        id=42,
        group_id=group_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые #1",
    )


def build(
    session: AthleteNotificationSession,
    **reader_kwargs: object,
) -> tuple[
    NotifyAthleteBeforeSessionInteractor,
    FakeReader,
    FakeDeliveryRepository,
    FakeNotifier,
    FrozenClock,
]:
    reader = FakeReader(session, **reader_kwargs)  # type: ignore[arg-type]
    deliveries = FakeDeliveryRepository()
    notifier = FakeNotifier()
    clock = FrozenClock()
    interactor = NotifyAthleteBeforeSessionInteractor(
        reader=reader,
        delivery_repository=deliveries,
        notifier=notifier,
        unit_of_work=FakeUnitOfWork(),
        clock=clock,
        club_timezone=CLUB_TIMEZONE,
    )
    return interactor, reader, deliveries, notifier, clock


async def test_discovery_uses_one_time_and_exact_windows() -> None:
    reader = FakeReader(None)
    reader.find_result = (AthleteNotificationCandidate(42, 9),)
    clock = FrozenClock()

    result = await FindAthletesForSessionReminderInteractor(reader, clock)()

    assert result.candidates == (AthleteNotificationCandidate(42, 9),)
    assert reader.find_args == (
        NOW,
        7200,
        600,
        NOW - timedelta(minutes=10),
    )
    assert clock.calls == 1


async def test_exact_due_sends_with_expected_key_and_fresh_projection() -> None:
    fresh = replace(
        make_session(),
        ends_at=NOW + timedelta(hours=4),
        group_name="Мини #1",
    )
    interactor, _, deliveries, notifier, clock = build(
        make_session(), fresh_session=fresh
    )

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is NotifyAthleteOutcome.SENT
    assert deliveries.claim_args is not None
    assert deliveries.claim_args["notification_type"] == "ATHLETE_SESSION_MINUS_2H"
    assert deliveries.claim_args["idempotency_key"] == (
        "ATHLETE_SESSION_MINUS_2H:42:9"
    )
    assert notifier.call is not None
    assert notifier.call[1].group_name == "Мини #1"
    assert notifier.call[1].ends_at == fresh.ends_at.astimezone(CLUB_TIMEZONE)
    assert clock.calls == 1


@pytest.mark.parametrize(
    ("starts_at", "outcome"),
    [
        (NOW + timedelta(hours=2, seconds=1), NotifyAthleteOutcome.NOT_DUE),
        (
            NOW + timedelta(hours=1, minutes=50),
            NotifyAthleteOutcome.WINDOW_EXPIRED,
        ),
        (
            NOW + timedelta(hours=1, minutes=50, seconds=1),
            NotifyAthleteOutcome.SENT,
        ),
    ],
)
async def test_narrow_window_boundaries(
    starts_at: datetime,
    outcome: NotifyAthleteOutcome,
) -> None:
    interactor, _, _, notifier, _ = build(make_session(starts_at=starts_at))

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is outcome
    assert (notifier.call is not None) is (outcome is NotifyAthleteOutcome.SENT)


async def test_moved_before_new_due_releases_owned_claim() -> None:
    interactor, _, deliveries, notifier, _ = build(
        make_session(),
        fresh_session=make_session(starts_at=NOW + timedelta(hours=3)),
    )

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is NotifyAthleteOutcome.NOT_DUE
    assert deliveries.released is True
    assert notifier.call is None


async def test_lost_eligibility_after_claim_releases_for_possible_later_eligibility() -> None:
    interactor, reader, deliveries, notifier, _ = build(make_session())
    reader.recipients[1] = None

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is NotifyAthleteOutcome.ATHLETE_INELIGIBLE
    assert deliveries.released is True
    assert notifier.call is None


async def test_retry_delay_that_reaches_window_end_is_terminal() -> None:
    interactor, _, deliveries, notifier, _ = build(
        make_session(starts_at=NOW + timedelta(hours=1, minutes=51))
    )
    notifier.error = RetryableNotificationSenderError(retry_after_seconds=60)

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is NotifyAthleteOutcome.TERMINAL_FAILED
    assert deliveries.failed is True


async def test_retry_inside_window_keeps_same_notification_ownership() -> None:
    interactor, _, deliveries, notifier, _ = build(make_session())
    notifier.error = RetryableNotificationSenderError()

    with pytest.raises(RetryableAthleteNotificationDeliveryError) as raised:
        await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert raised.value.notification_id == 100
    assert raised.value.delivery_attempt == 1
    assert deliveries.failed is False


async def test_fresh_retry_after_window_is_terminal_without_send() -> None:
    interactor, _, deliveries, notifier, _ = build(
        make_session(starts_at=NOW + timedelta(hours=1, minutes=50))
    )
    deliveries.claim_result = NotificationClaim(
        NotificationClaimOutcome.ACQUIRED,
        attempts=2,
        notification_id=100,
    )

    result = await interactor(
        NotifyAthleteBeforeSessionCommand(
            42,
            9,
            delivery_attempt=2,
            notification_id=100,
        )
    )

    assert result.outcome is NotifyAthleteOutcome.WINDOW_EXPIRED
    assert deliveries.failed is True
    assert notifier.call is None


async def test_missing_telegram_after_claim_is_terminal() -> None:
    interactor, reader, deliveries, notifier, _ = build(make_session())
    reader.recipients[1] = AthleteNotificationRecipient(9, 7, None)

    result = await interactor(NotifyAthleteBeforeSessionCommand(42, 9))

    assert result.outcome is NotifyAthleteOutcome.TELEGRAM_UNAVAILABLE
    assert deliveries.failed is True
    assert notifier.call is None
