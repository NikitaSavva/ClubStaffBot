import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.athlete_notifications import (
    AthleteNotificationMessage,
    NotifyAthleteBeforeSessionCommand,
    NotifyAthleteBeforeSessionInteractor,
    NotifyAthleteBeforeSessionResult,
    NotifyAthleteOutcome,
    RetryableAthleteNotificationDeliveryError,
)
from application.notification_delivery import RetryableNotificationSenderError
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from infrastructure.database.athlete_notifications import (
    SqlAlchemyAthleteNotificationReader,
)
from infrastructure.database.models import (
    AthleteModel,
    GroupNameModel,
    NotificationModel,
    NotificationStatus,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.notification_delivery import (
    SqlAlchemyNotificationDeliveryRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)
CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class RecordingNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, AthleteNotificationMessage]] = []

    async def send(
        self,
        *,
        telegram_id: int,
        message: AthleteNotificationMessage,
    ) -> None:
        self.calls.append((telegram_id, message))
        if self.error is not None:
            raise self.error


class MutatingAthleteNotificationReader(SqlAlchemyAthleteNotificationReader):
    def __init__(
        self,
        session: AsyncSession,
        mutation: Callable[[], Awaitable[None]] | None,
    ) -> None:
        super().__init__(session)
        self._mutation = mutation
        self._session_calls = 0

    async def get_session(self, training_session_id: int):
        self._session_calls += 1
        if self._session_calls == 2 and self._mutation is not None:
            await self._mutation()
        return await super().get_session(training_session_id)


@dataclass(frozen=True, slots=True)
class Context:
    trainer_id: int
    athlete_user_id: int
    athlete_id: int
    direction_id: int
    group_name_id: int
    group_id: int
    plan_id: int
    subscription_id: int
    training_session_id: int


async def setup(factory: async_sessionmaker[AsyncSession]) -> Context:
    suffix = uuid4().hex[:8]
    async with factory.begin() as session:
        trainer = UserModel(
            telegram_id=610_000_000 + uuid4().int % 10_000_000,
            username=f"trainer_{suffix}",
            first_name="Trainer",
            last_name=suffix,
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        athlete_user = UserModel(
            telegram_id=620_000_000 + uuid4().int % 10_000_000,
            username=f"athlete_{suffix}",
            first_name="Athlete",
            last_name=suffix,
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        direction = SportDirectionModel(
            code=f"ATH_DELIVERY_{suffix}",
            name="Кикбоксинг",
            short_name=None,
            is_active=True,
        )
        group_name = GroupNameModel(name=f"Взрослые {suffix}")
        plan = SubscriptionPlanModel(
            code=f"ATH_DELIVERY_PLAN_{suffix}",
            name="8 занятий",
            visit_limit=8,
            duration_months=1,
            price=Decimal("4000"),
            is_unlimited=False,
            access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
            required_group_type=None,
            is_active=True,
        )
        session.add_all([trainer, athlete_user, direction, group_name, plan])
        await session.flush()
        group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=trainer.id,
            name_id=group_name.id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        athlete = AthleteModel(
            user_id=athlete_user.id,
            first_name="Athlete",
            last_name=suffix,
            birth_date=date(1990, 1, 1),
            phone=None,
            is_active=True,
        )
        session.add_all([group, athlete])
        await session.flush()
        subscription = SubscriptionModel(
            athlete_id=athlete.id,
            group_id=group.id,
            plan_id=plan.id,
            activated_by_user_id=trainer.id,
            activated_at=NOW - timedelta(days=1),
            starts_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=1),
            activation_price=plan.price,
            remaining_visits=8,
            status=SubscriptionStatus.ACTIVE,
        )
        training_session = TrainingSessionModel(
            schedule_rule_id=None,
            group_id=group.id,
            trainer_id=trainer.id,
            starts_at=NOW + timedelta(hours=2),
            ends_at=NOW + timedelta(hours=3, minutes=30),
            status=TrainingSessionStatus.SCHEDULED,
            is_overridden=False,
        )
        session.add_all([subscription, training_session])
        await session.flush()
        return Context(
            trainer_id=trainer.id,
            athlete_user_id=athlete_user.id,
            athlete_id=athlete.id,
            direction_id=direction.id,
            group_name_id=group_name.id,
            group_id=group.id,
            plan_id=plan.id,
            subscription_id=subscription.id,
            training_session_id=training_session.id,
        )


async def cleanup(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> None:
    async with factory.begin() as session:
        await session.execute(
            delete(NotificationModel).where(
                NotificationModel.recipient_user_id == context.athlete_user_id,
                NotificationModel.type == "ATHLETE_SESSION_MINUS_2H",
            )
        )
        await session.execute(
            delete(TrainingSessionModel).where(
                TrainingSessionModel.group_id == context.group_id
            )
        )
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.id == context.subscription_id
            )
        )
        await session.execute(
            delete(AthleteModel).where(AthleteModel.id == context.athlete_id)
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id == context.group_id
            )
        )
        await session.execute(
            delete(SubscriptionPlanModel).where(
                SubscriptionPlanModel.id == context.plan_id
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
            delete(UserModel).where(
                UserModel.id.in_((context.trainer_id, context.athlete_user_id))
            )
        )


async def process(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
    notifier: RecordingNotifier,
    *,
    command: NotifyAthleteBeforeSessionCommand | None = None,
    mutation: Callable[[], Awaitable[None]] | None = None,
) -> NotifyAthleteBeforeSessionResult:
    async with factory() as session:
        return await NotifyAthleteBeforeSessionInteractor(
            reader=MutatingAthleteNotificationReader(session, mutation),
            delivery_repository=SqlAlchemyNotificationDeliveryRepository(session),
            notifier=notifier,
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
            club_timezone=CLUB_TIMEZONE,
        )(
            command
            or NotifyAthleteBeforeSessionCommand(
                context.training_session_id,
                context.athlete_id,
            )
        )


async def get_notification(
    factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> NotificationModel | None:
    async with factory() as session:
        return await session.scalar(
            select(NotificationModel).where(
                NotificationModel.idempotency_key
                == (
                    "ATHLETE_SESSION_MINUS_2H:"
                    f"{context.training_session_id}:{context.athlete_id}"
                )
            )
        )


async def test_sequential_and_concurrent_processing_send_once(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    first_context = await setup(factory)
    second_context = await setup(factory)
    try:
        notifier = RecordingNotifier()
        first = await process(factory, first_context, notifier)
        repeated = await process(factory, first_context, notifier)
        assert first.outcome is NotifyAthleteOutcome.SENT
        assert repeated.outcome is NotifyAthleteOutcome.ALREADY_SENT
        assert len(notifier.calls) == 1

        concurrent_notifier = RecordingNotifier()
        concurrent = await asyncio.gather(
            process(factory, second_context, concurrent_notifier),
            process(factory, second_context, concurrent_notifier),
        )
        assert sum(item.outcome is NotifyAthleteOutcome.SENT for item in concurrent) == 1
        assert len(concurrent_notifier.calls) == 1
        notification = await get_notification(factory, second_context)
        assert notification is not None
        assert notification.status is NotificationStatus.SENT
        assert notification.idempotency_key.endswith(
            f":{second_context.training_session_id}:{second_context.athlete_id}"
        )
    finally:
        await cleanup(factory, first_context)
        await cleanup(factory, second_context)
        await engine.dispose()


async def test_retry_continuation_uses_same_notification_and_then_succeeds(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier(RetryableNotificationSenderError())
    try:
        with pytest.raises(RetryableAthleteNotificationDeliveryError) as raised:
            await process(factory, context, notifier)
        first_id = raised.value.notification_id
        notifier.error = None
        result = await process(
            factory,
            context,
            notifier,
            command=NotifyAthleteBeforeSessionCommand(
                context.training_session_id,
                context.athlete_id,
                delivery_attempt=2,
                notification_id=first_id,
            ),
        )
        notification = await get_notification(factory, context)

        assert result.outcome is NotifyAthleteOutcome.SENT
        assert result.notification_id == first_id
        assert notification is not None
        assert notification.id == first_id
        assert notification.attempts == 2
        assert notification.status is NotificationStatus.SENT
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_logical_keys_are_independent_per_athlete_and_session(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    try:
        async with factory.begin() as session:
            second_session = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=context.group_id,
                trainer_id=context.trainer_id,
                starts_at=NOW + timedelta(hours=2, minutes=5),
                ends_at=NOW + timedelta(hours=3, minutes=35),
                status=TrainingSessionStatus.SCHEDULED,
                is_overridden=False,
            )
            session.add(second_session)
            await session.flush()
            repository = SqlAlchemyNotificationDeliveryRepository(session)
            claims = []
            for session_id, athlete_id in (
                (context.training_session_id, context.athlete_id),
                (context.training_session_id, context.athlete_id + 1000),
                (second_session.id, context.athlete_id),
            ):
                claims.append(
                    await repository.claim(
                        notification_type="ATHLETE_SESSION_MINUS_2H",
                        training_session_id=session_id,
                        recipient_user_id=context.athlete_user_id,
                        scheduled_at=NOW,
                        idempotency_key=(
                            f"ATHLETE_SESSION_MINUS_2H:{session_id}:{athlete_id}"
                        ),
                        delivery_attempt=1,
                        notification_id=None,
                        stale_pending_before=NOW - timedelta(minutes=10),
                        max_attempts=4,
                        reference_now=NOW,
                    )
                )

        assert len({claim.notification_id for claim in claims}) == 3
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_post_claim_moved_session_releases_then_uses_new_window(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()

    async def move_outside_window() -> None:
        async with factory.begin() as session:
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(starts_at=NOW + timedelta(hours=3))
            )

    try:
        released = await process(
            factory,
            context,
            notifier,
            mutation=move_outside_window,
        )
        assert released.outcome is NotifyAthleteOutcome.NOT_DUE
        assert await get_notification(factory, context) is None
        assert notifier.calls == []

        async with factory.begin() as session:
            await session.execute(
                update(TrainingSessionModel)
                .where(TrainingSessionModel.id == context.training_session_id)
                .values(starts_at=NOW + timedelta(hours=2))
            )
        sent = await process(factory, context, notifier)
        assert sent.outcome is NotifyAthleteOutcome.SENT
        assert len(notifier.calls) == 1
    finally:
        await cleanup(factory, context)
        await engine.dispose()


async def test_post_claim_lost_eligibility_releases_without_subscription_write(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    context = await setup(factory)
    notifier = RecordingNotifier()

    async def exhaust_subscription() -> None:
        async with factory.begin() as session:
            await session.execute(
                update(SubscriptionModel)
                .where(SubscriptionModel.id == context.subscription_id)
                .values(remaining_visits=0)
            )

    try:
        result = await process(
            factory,
            context,
            notifier,
            mutation=exhaust_subscription,
        )
        assert result.outcome is NotifyAthleteOutcome.ATHLETE_INELIGIBLE
        assert await get_notification(factory, context) is None
        async with factory() as session:
            subscription = await session.get(
                SubscriptionModel,
                context.subscription_id,
            )
        assert subscription is not None
        assert subscription.status is SubscriptionStatus.ACTIVE
        assert subscription.remaining_visits == 0
        assert notifier.calls == []
    finally:
        await cleanup(factory, context)
        await engine.dispose()
