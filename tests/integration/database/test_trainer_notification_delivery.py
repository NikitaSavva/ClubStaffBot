import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.trainer_notifications import TrainerNotificationClaimOutcome
from domain.club import TrainingGroupType, TrainingSessionStatus
from infrastructure.database.models import (
    GroupNameModel,
    NotificationModel,
    SportDirectionModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.trainer_notifications import (
    SqlAlchemyTrainerNotificationDeliveryRepository,
)
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 2, 15, 55, tzinfo=UTC)


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
                stale_pending_before=reference_now - timedelta(minutes=10),
                max_attempts=4,
                reference_now=reference_now,
            )
            await uow.commit()
            return result


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

        retries = await asyncio.gather(
            claim(factory, context, delivery_attempt=2),
            claim(factory, context, delivery_attempt=2),
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
