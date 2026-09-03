import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.trainer_notifications import (
    NotifyTrainerBeforeSessionCommand,
    NotifyTrainerBeforeSessionInteractor,
    NotifyTrainerBeforeSessionResult,
    NotifyTrainerOutcome,
    PermanentTrainerNotifierError,
    RetryableTrainerNotificationDeliveryError,
    RetryableTrainerNotifierError,
    TrainerNotificationClaimOutcome,
    TrainerNotificationMessage,
)
from domain.club import TrainingGroupType, TrainingSessionStatus
from infrastructure.database.models import (
    GroupNameModel,
    NotificationModel,
    NotificationStatus,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.trainer_notifications import (
    SqlAlchemyTrainerNotificationDeliveryRepository,
    SqlAlchemyTrainerNotificationReader,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 2, 15, 55, tzinfo=UTC)
CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class RecordingNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, TrainerNotificationMessage]] = []

    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None:
        self.calls.append((telegram_id, message))
        if self.error is not None:
            raise self.error


class MutatingTrainerNotificationReader(SqlAlchemyTrainerNotificationReader):
    def __init__(
        self,
        session: AsyncSession,
        mutation: Callable[[], Awaitable[None]] | None,
    ) -> None:
        super().__init__(session)
        self._mutation = mutation
        self._get_calls = 0

    async def get_session(self, training_session_id: int):
        self._get_calls += 1
        if self._get_calls == 2 and self._mutation is not None:
            await self._mutation()
        return await super().get_session(training_session_id)


@dataclass(frozen=True, slots=True)
class Context:
    user_id: int
    direction_id: int
    group_name_id: int
    group_id: int
    training_session_id: int


async def setup(
    factory: async_sessionmaker[AsyncSession],
) -> Context:
    suffix = uuid4().hex[:8]
    async with factory.begin() as session:
        user = UserModel(
            telegram_id=600_000_000 + uuid4().int % 200_000_000,
            username=f"delivery_{suffix}",
            first_name="Trainer",
            last_name=suffix,
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        direction = SportDirectionModel(
            code=f"DELIVERY_{suffix}",
            name=f"Direction {suffix}",
            short_name=None,
            is_active=True,
        )
        group_name = GroupNameModel(name=f"Delivery {suffix}")
        session.add_all([user, direction, group_name])
        await session.flush()
        group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=user.id,
            name_id=group_name.id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        session.add(group)
        await session.flush()
        training_session = TrainingSessionModel(
            schedule_rule_id=None,
            group_id=group.id,
            trainer_id=user.id,
            starts_at=NOW + timedelta(minutes=5),
            ends_at=NOW + timedelta(hours=1, minutes=35),
            status=TrainingSessionStatus.SCHEDULED,
            is_overridden=False,
        )
        session.add(training_session)
        await session.flush()
        return Context(
            user_id=user.id,
            direction_id=direction.id,
            group_name_id=group_name.id,
            group_id=group.id,
            training_session_id=training_session.id,
        )


async def cleanup(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> None:
    async with factory.begin() as session:
        await session.execute(
            delete(NotificationModel).where(
                NotificationModel.training_session_id
                == context.training_session_id
            )
        )
        await session.execute(
            delete(TrainingSessionModel).where(
                TrainingSessionModel.id == context.training_session_id
            )
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id == context.group_id
            )
        )
        await session.execute(
            delete(GroupNameModel).where(
                GroupNameModel.id == context.group_name_id
            )
        )
        await session.execute(
            delete(SportDirectionModel).where(
                SportDirectionModel.id == context.direction_id
            )
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == context.user_id)
        )


async def claim(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
    *,
    delivery_attempt: int,
    notification_id: int | None = None,
    reference_now: datetime = NOW,
):
    async with factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        async with uow:
            result = await SqlAlchemyTrainerNotificationDeliveryRepository(
                session
            ).claim(
                training_session_id=context.training_session_id,
                recipient_user_id=context.user_id,
                scheduled_at=NOW,
                idempotency_key=(
                    "TRAINER_SESSION_MINUS_5:"
                    f"{context.training_session_id}"
                ),
                delivery_attempt=delivery_attempt,
                notification_id=notification_id,
                stale_pending_before=reference_now - timedelta(minutes=10),
                max_attempts=4,
                reference_now=reference_now,
            )
            await uow.commit()
            return result


async def process_notification(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
    notifier: RecordingNotifier,
    *,
    command: NotifyTrainerBeforeSessionCommand | None = None,
    mutation: Callable[[], Awaitable[None]] | None = None,
) -> NotifyTrainerBeforeSessionResult:
    async with factory() as session:
        return await NotifyTrainerBeforeSessionInteractor(
            reader=MutatingTrainerNotificationReader(session, mutation),
            delivery_repository=SqlAlchemyTrainerNotificationDeliveryRepository(
                session
            ),
            notifier=notifier,
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
            club_timezone=CLUB_TIMEZONE,
        )(
            command
            or NotifyTrainerBeforeSessionCommand(
                training_session_id=context.training_session_id
            )
        )


async def get_notification(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> NotificationModel:
    async with factory() as session:
        notification = await session.scalar(
            select(NotificationModel).where(
                NotificationModel.training_session_id
                == context.training_session_id
            )
        )
        assert notification is not None
        return notification


async def test_concurrent_initial_and_numbered_retry_have_one_claim(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    try:
        initial = await asyncio.gather(
            claim(factory, context, delivery_attempt=1),
            claim(factory, context, delivery_attempt=1),
        )
        assert sorted(item.outcome for item in initial) == [
            TrainerNotificationClaimOutcome.ACQUIRED,
            TrainerNotificationClaimOutcome.IN_PROGRESS,
        ]
        acquired = next(
            item
            for item in initial
            if item.outcome is TrainerNotificationClaimOutcome.ACQUIRED
        )
        assert acquired.notification_id is not None

        retries = await asyncio.gather(
            claim(
                factory,
                context,
                delivery_attempt=2,
                notification_id=acquired.notification_id,
            ),
            claim(
                factory,
                context,
                delivery_attempt=2,
                notification_id=acquired.notification_id,
            ),
        )
        assert sorted(item.outcome for item in retries) == [
            TrainerNotificationClaimOutcome.ACQUIRED,
            TrainerNotificationClaimOutcome.IN_PROGRESS,
        ]

        async with factory() as session:
            rows = await session.scalar(
                select(func.count())
                .select_from(NotificationModel)
                .where(
                    NotificationModel.training_session_id
                    == context.training_session_id
                )
            )
            attempts = await session.scalar(
                select(NotificationModel.attempts).where(
                    NotificationModel.training_session_id
                    == context.training_session_id
                )
            )
        assert rows == 1
        assert attempts == 2
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_polling_cannot_reclaim_before_ten_minute_crash_lease(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    try:
        acquired = await claim(factory, context, delivery_attempt=1)
        fresh = await claim(
            factory,
            context,
            delivery_attempt=1,
            reference_now=NOW + timedelta(minutes=9, seconds=59),
        )
        assert acquired.outcome is TrainerNotificationClaimOutcome.ACQUIRED
        assert fresh.outcome is TrainerNotificationClaimOutcome.IN_PROGRESS

        async with factory.begin() as session:
            await session.execute(
                update(NotificationModel)
                .where(
                    NotificationModel.training_session_id
                    == context.training_session_id
                )
                .values(updated_at=NOW - timedelta(minutes=11))
            )
        stale = await claim(factory, context, delivery_attempt=1)
        assert stale.outcome is TrainerNotificationClaimOutcome.ACQUIRED
        assert stale.attempts == 2
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_exhausted_stale_pending_is_committed_as_failed(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()
    try:
        async with factory.begin() as session:
            session.add(
                NotificationModel(
                    recipient_user_id=context.user_id,
                    training_session_id=context.training_session_id,
                    type="TRAINER_SESSION_MINUS_5",
                    scheduled_at=NOW,
                    sent_at=None,
                    status=NotificationStatus.PENDING,
                    idempotency_key=(
                        "TRAINER_SESSION_MINUS_5:"
                        f"{context.training_session_id}"
                    ),
                    attempts=4,
                    created_at=NOW - timedelta(minutes=11),
                    updated_at=NOW - timedelta(minutes=11),
                )
            )

        result = await process_notification(factory, context, notifier)
        notification = await get_notification(factory, context)

        assert result.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert result.attempts == 4
        assert notification.status is NotificationStatus.FAILED
        assert notifier.calls == []
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_released_row_identity_cannot_mutate_reinserted_claim(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    key = f"TRAINER_SESSION_MINUS_5:{context.training_session_id}"
    try:
        old_claim = await claim(factory, context, delivery_attempt=1)
        assert old_claim.notification_id is not None

        async with factory() as session:
            uow = SqlAlchemyUnitOfWork(session)
            async with uow:
                released = await (
                    SqlAlchemyTrainerNotificationDeliveryRepository(session)
                ).release_pending(
                    notification_id=old_claim.notification_id,
                    idempotency_key=key,
                    expected_attempts=1,
                )
                await uow.commit()
        assert released is True

        new_claim = await claim(factory, context, delivery_attempt=1)
        assert new_claim.notification_id is not None
        assert new_claim.notification_id != old_claim.notification_id

        async with factory() as session:
            repository = SqlAlchemyTrainerNotificationDeliveryRepository(session)
            uow = SqlAlchemyUnitOfWork(session)
            async with uow:
                stale_release = await repository.release_pending(
                    notification_id=old_claim.notification_id,
                    idempotency_key=key,
                    expected_attempts=1,
                )
                stale_sent = await repository.mark_sent(
                    notification_id=old_claim.notification_id,
                    idempotency_key=key,
                    attempts=1,
                    sent_at=NOW,
                )
                stale_failed = await repository.mark_failed(
                    notification_id=old_claim.notification_id,
                    idempotency_key=key,
                    expected_attempts=1,
                    reference_now=NOW,
                )
                await uow.commit()

        assert stale_release is False
        assert stale_sent is False
        assert stale_failed is False

        stale_retry = await claim(
            factory,
            context,
            delivery_attempt=2,
            notification_id=old_claim.notification_id,
        )
        assert stale_retry.outcome is TrainerNotificationClaimOutcome.IN_PROGRESS

        async with factory() as session:
            row = await session.scalar(
                select(NotificationModel).where(
                    NotificationModel.id == new_claim.notification_id
                )
            )
            assert row is not None
            assert row.status.value == "PENDING"
            assert row.attempts == 1
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_sequential_processing_persists_sent_and_sends_once(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()
    try:
        first = await process_notification(factory, context, notifier)
        notification = await get_notification(factory, context)

        assert first.outcome is NotifyTrainerOutcome.SENT
        assert notification.status is NotificationStatus.SENT
        assert notification.sent_at == NOW
        assert notification.attempts == 1

        second = await process_notification(factory, context, notifier)

        assert second.outcome is NotifyTrainerOutcome.ALREADY_SENT
        assert second.attempts == 1
        assert len(notifier.calls) == 1
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_concurrent_processing_sends_once_and_persists_sent(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()
    try:
        results = await asyncio.gather(
            process_notification(factory, context, notifier),
            process_notification(factory, context, notifier),
        )
        notification = await get_notification(factory, context)

        assert sum(
            result.outcome is NotifyTrainerOutcome.SENT for result in results
        ) == 1
        assert all(
            result.outcome
            in {
                NotifyTrainerOutcome.SENT,
                NotifyTrainerOutcome.IN_PROGRESS,
                NotifyTrainerOutcome.ALREADY_SENT,
            }
            for result in results
        )
        assert len(notifier.calls) == 1
        assert notification.status is NotificationStatus.SENT
        assert notification.sent_at == NOW
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_permanent_failure_is_persisted_and_never_resent(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier(PermanentTrainerNotifierError())
    try:
        first = await process_notification(factory, context, notifier)
        notification = await get_notification(factory, context)

        assert first.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert notification.status is NotificationStatus.FAILED
        assert notification.attempts == 1

        second = await process_notification(factory, context, notifier)

        assert second.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert second.attempts == 1
        assert len(notifier.calls) == 1
    finally:
        await cleanup(factory, context)
        await engine.dispose()


@pytest.mark.parametrize(
    ("cancelled", "outcome"),
    [
        (True, NotifyTrainerOutcome.CANCELLED),
        (False, NotifyTrainerOutcome.SESSION_STARTED),
    ],
)
async def test_post_claim_terminal_recheck_persists_failed(
    database_url: str,
    cancelled: bool,
    outcome: NotifyTrainerOutcome,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()

    async def mutate_after_claim() -> None:
        values: dict[str, object]
        if cancelled:
            values = {"status": TrainingSessionStatus.CANCELLED}
        else:
            values = {
                "starts_at": NOW,
                "ends_at": NOW + timedelta(hours=1),
            }
        async with factory.begin() as session:
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(**values)
            )

    try:
        result = await process_notification(
            factory,
            context,
            notifier,
            mutation=mutate_after_claim,
        )
        notification = await get_notification(factory, context)

        assert result.outcome is outcome
        assert notification.status is NotificationStatus.FAILED
        assert notifier.calls == []

        repeated = await process_notification(factory, context, notifier)
        assert repeated.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert notifier.calls == []
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_post_claim_moved_session_releases_only_owned_row(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()

    async def move_outside_due_window() -> None:
        async with factory.begin() as session:
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(
                    starts_at=NOW + timedelta(minutes=20),
                    ends_at=NOW + timedelta(hours=1, minutes=50),
                )
            )

    try:
        released = await process_notification(
            factory,
            context,
            notifier,
            mutation=move_outside_due_window,
        )
        assert released.outcome is NotifyTrainerOutcome.NOT_DUE
        assert released.notification_id is not None
        assert notifier.calls == []

        async with factory.begin() as session:
            remaining = await session.scalar(
                select(func.count())
                .select_from(NotificationModel)
                .where(
                    NotificationModel.training_session_id
                    == context.training_session_id
                )
            )
            assert remaining == 0
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(
                    starts_at=NOW + timedelta(minutes=5),
                    ends_at=NOW + timedelta(hours=1, minutes=35),
                )
            )

        sent = await process_notification(factory, context, notifier)
        assert sent.outcome is NotifyTrainerOutcome.SENT
        assert sent.notification_id != released.notification_id
        assert len(notifier.calls) == 1
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_post_claim_trainer_and_times_use_fresh_session_snapshot(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()
    replacement_user_id: int | None = None
    replacement_telegram_id: int | None = None
    fresh_start = NOW + timedelta(minutes=4)
    fresh_end = fresh_start + timedelta(hours=2)

    async with factory.begin() as session:
        replacement = UserModel(
            telegram_id=800_000_000 + uuid4().int % 100_000_000,
            username=f"replacement_{uuid4().hex[:8]}",
            first_name="Replacement",
            last_name="Trainer",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(replacement)
        await session.flush()
        replacement_user_id = replacement.id
        replacement_telegram_id = replacement.telegram_id

    async def replace_snapshot_after_claim() -> None:
        async with factory.begin() as session:
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(
                    trainer_id=replacement_user_id,
                    starts_at=fresh_start,
                    ends_at=fresh_end,
                )
            )

    try:
        result = await process_notification(
            factory,
            context,
            notifier,
            mutation=replace_snapshot_after_claim,
        )
        notification = await get_notification(factory, context)

        assert result.outcome is NotifyTrainerOutcome.SENT
        assert len(notifier.calls) == 1
        telegram_id, message = notifier.calls[0]
        assert telegram_id == replacement_telegram_id
        assert message.starts_at == fresh_start.astimezone(CLUB_TIMEZONE)
        assert message.ends_at == fresh_end.astimezone(CLUB_TIMEZONE)
        assert notification.recipient_user_id == replacement_user_id
        assert notification.scheduled_at == fresh_start - timedelta(minutes=5)
    finally:
        await cleanup(factory, context)
        if replacement_user_id is not None:
            async with factory.begin() as session:
                await session.execute(
                    delete(UserModel).where(UserModel.id == replacement_user_id)
                )
        await engine.dispose()


async def test_retry_attempts_persist_and_exhaustion_is_terminal(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier(RetryableTrainerNotifierError())
    command = NotifyTrainerBeforeSessionCommand(context.training_session_id)
    try:
        notification_id: int | None = None
        for expected_attempt in (1, 2, 3):
            with pytest.raises(
                RetryableTrainerNotificationDeliveryError
            ) as raised:
                await process_notification(
                    factory,
                    context,
                    notifier,
                    command=command,
                )
            notification_id = raised.value.notification_id
            notification = await get_notification(factory, context)
            assert notification.id == notification_id
            assert notification.attempts == expected_attempt
            assert notification.status is NotificationStatus.PENDING
            command = NotifyTrainerBeforeSessionCommand(
                context.training_session_id,
                delivery_attempt=expected_attempt + 1,
                notification_id=notification_id,
            )

        exhausted = await process_notification(
            factory,
            context,
            notifier,
            command=command,
        )
        notification = await get_notification(factory, context)

        assert exhausted.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert exhausted.attempts == 4
        assert notification.status is NotificationStatus.FAILED
        assert notification.attempts == 4

        repeated = await process_notification(factory, context, notifier)
        assert repeated.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
        assert len(notifier.calls) == 4
    finally:
        await cleanup(factory, context)
        await engine.dispose()


@pytest.mark.parametrize(
    ("retry_after", "raises_retry"),
    [(90, True), (300, False)],
)
async def test_retry_after_allowed_and_too_late_persistence(
    database_url: str,
    retry_after: int,
    raises_retry: bool,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier(
        RetryableTrainerNotifierError(retry_after_seconds=retry_after)
    )
    try:
        if raises_retry:
            with pytest.raises(RetryableTrainerNotificationDeliveryError) as error:
                await process_notification(factory, context, notifier)
            assert error.value.retry_after_seconds == retry_after
            notification = await get_notification(factory, context)
            assert notification.status is NotificationStatus.PENDING
        else:
            result = await process_notification(factory, context, notifier)
            notification = await get_notification(factory, context)
            assert result.outcome is NotifyTrainerOutcome.TERMINAL_FAILED
            assert notification.status is NotificationStatus.FAILED
    finally:
        await cleanup(factory, context)
        await engine.dispose()
