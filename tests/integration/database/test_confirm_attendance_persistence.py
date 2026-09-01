import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.attendance import (
    ConfirmAttendanceCommand,
    ConfirmAttendanceInteractor,
    ConfirmAttendanceOutcome,
)
from application.scanner import (
    ConfirmAttendanceByQrInteractor,
    TrustedTelegramWebAppUser,
)
from domain.attendance import AttendanceSource, AttendanceStatus
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.identity import SystemRoleCode
from domain.subscriptions import (
    SubscriptionAccessScope,
    SubscriptionStatus,
)
from infrastructure.database.models import (
    AthleteModel,
    AttendanceModel,
    AuditLogModel,
    GroupNameModel,
    RoleModel,
    SportDirectionModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    TrainingSessionModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.repositories import (
    SqlAlchemyAthleteRepository,
    SqlAlchemyAttendanceRepository,
    SqlAlchemyAttendanceSessionRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySubscriptionPlanRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from presentation.api.scanner import confirm_attendance_by_qr_request
from presentation.api.schemas import ScannerAttendanceRequest

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class TrustedVerifier:
    def __init__(self, telegram_user_id: int) -> None:
        self.telegram_user_id = telegram_user_id

    def verify(self, raw_init_data: str) -> TrustedTelegramWebAppUser:
        assert raw_init_data == "signed-init-data"
        return TrustedTelegramWebAppUser(
            telegram_user_id=self.telegram_user_id
        )


class AthletePublicIdCodec:
    def __init__(self, athlete_public_id: UUID) -> None:
        self.athlete_public_id = athlete_public_id

    def verify(self, token: str) -> UUID:
        assert token == "signed-athlete-token"
        return self.athlete_public_id


@dataclass(frozen=True, slots=True)
class Context:
    actor_telegram_id: int
    actor_id: int
    athlete_id: int
    athlete_public_id: UUID
    direction_id: int
    group_name_id: int
    group_id: int
    plan_id: int
    subscription_id: int
    training_session_id: int


async def ensure_admin_role(session: AsyncSession) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(
            RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
        )
    )
    if role is None:
        role = RoleModel(
            code=SystemRoleCode.ADMINISTRATOR.value,
            name="Administrator",
            is_system=True,
            is_active=True,
        )
        session.add(role)
        await session.flush()
    return role


async def setup_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    remaining_visits: int = 8,
    expires_at: datetime = NOW + timedelta(days=10),
) -> Context:
    suffix = uuid4().hex[:10]
    async with session_factory() as session:
        role = await ensure_admin_role(session)
        actor = UserModel(
            telegram_id=80_000_000 + uuid4().int % 1_000_000_000,
            username=f"attendance_admin_{suffix}",
            first_name="Admin",
            last_name=suffix,
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        athlete = AthleteModel(
            user_id=None,
            first_name="Иван",
            last_name=suffix,
            birth_date=date(1991, 12, 27),
            phone=None,
            is_active=True,
        )
        direction = SportDirectionModel(
            code=f"ATT_{suffix}",
            name=f"Кикбоксинг {suffix}",
            short_name=None,
            is_active=True,
        )
        group_name = GroupNameModel(name=f"Взрослые ATT {suffix}")
        plan = SubscriptionPlanModel(
            code=f"ATT_PLAN_{suffix}",
            name="8 посещений",
            visit_limit=8,
            duration_months=1,
            price=Decimal("4000"),
            is_unlimited=False,
            access_scope=SubscriptionAccessScope.SPECIFIC_GROUP,
            required_group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        session.add_all([actor, athlete, direction, group_name, plan])
        await session.flush()
        session.add(
            UserRoleModel(
                user_id=actor.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )
        group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=actor.id,
            name_id=group_name.id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        session.add(group)
        await session.flush()
        subscription = SubscriptionModel(
            athlete_id=athlete.id,
            group_id=group.id,
            plan_id=plan.id,
            activated_by_user_id=actor.id,
            activated_at=NOW - timedelta(days=1),
            starts_at=NOW - timedelta(days=1),
            expires_at=expires_at,
            activation_price=plan.price,
            remaining_visits=remaining_visits,
            status=SubscriptionStatus.ACTIVE,
        )
        training_session = TrainingSessionModel(
            schedule_rule_id=None,
            group_id=group.id,
            trainer_id=actor.id,
            starts_at=NOW + timedelta(hours=4),
            ends_at=NOW + timedelta(hours=5, minutes=30),
            status=TrainingSessionStatus.SCHEDULED,
            is_overridden=False,
        )
        session.add_all([subscription, training_session])
        await session.commit()
        return Context(
            actor_telegram_id=actor.telegram_id,
            actor_id=actor.id,
            athlete_id=athlete.id,
            athlete_public_id=athlete.athlete_public_id,
            direction_id=direction.id,
            group_name_id=group_name.id,
            group_id=group.id,
            plan_id=plan.id,
            subscription_id=subscription.id,
            training_session_id=training_session.id,
        )


async def execute_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> ConfirmAttendanceOutcome:
    async with session_factory() as session:
        result = await ConfirmAttendanceInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            subscription_repository=SqlAlchemySubscriptionRepository(session),
            subscription_plan_repository=(
                SqlAlchemySubscriptionPlanRepository(session)
            ),
            training_session_repository=(
                SqlAlchemyAttendanceSessionRepository(session)
            ),
            attendance_repository=SqlAlchemyAttendanceRepository(session),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
            club_timezone=CLUB_TIMEZONE,
        )(
            ConfirmAttendanceCommand(
                actor_telegram_id=context.actor_telegram_id,
                athlete_public_id=context.athlete_public_id,
                source=AttendanceSource.QR,
            )
        )
        return result.outcome


async def execute_api_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
    context: Context,
):  # type: ignore[no-untyped-def]
    async with session_factory() as session:
        core = ConfirmAttendanceInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            athlete_repository=SqlAlchemyAthleteRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            subscription_repository=SqlAlchemySubscriptionRepository(session),
            subscription_plan_repository=(
                SqlAlchemySubscriptionPlanRepository(session)
            ),
            training_session_repository=(
                SqlAlchemyAttendanceSessionRepository(session)
            ),
            attendance_repository=SqlAlchemyAttendanceRepository(session),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
            clock=FrozenClock(),
            club_timezone=CLUB_TIMEZONE,
        )
        return await confirm_attendance_by_qr_request(
            request=ScannerAttendanceRequest(token="signed-athlete-token"),
            telegram_init_data="signed-init-data",
            verifier=TrustedVerifier(context.actor_telegram_id),
            interactor=ConfirmAttendanceByQrInteractor(
                token_codec=AthletePublicIdCodec(context.athlete_public_id),
                confirm_attendance=core,
            ),
        )


async def cleanup_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: Context,
) -> None:
    async with session_factory() as session:
        attendance_ids = tuple(
            await session.scalars(
                select(AttendanceModel.id).where(
                    AttendanceModel.athlete_id == context.athlete_id
                )
            )
        )
        if attendance_ids:
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.entity_type == "ATTENDANCE",
                    AuditLogModel.entity_id.in_(attendance_ids),
                )
            )
        await session.execute(
            delete(AuditLogModel).where(
                AuditLogModel.entity_type == "SUBSCRIPTION",
                AuditLogModel.entity_id == context.subscription_id,
            )
        )
        await session.execute(
            delete(AttendanceModel).where(
                AttendanceModel.athlete_id == context.athlete_id
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
            delete(UserRoleModel).where(
                UserRoleModel.user_id == context.actor_id
            )
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
            delete(AthleteModel).where(AthleteModel.id == context.athlete_id)
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == context.actor_id)
        )
        await session.commit()


@pytest.mark.parametrize(
    ("remaining_visits", "expires_at", "expected_code", "reason"),
    [
        (5, NOW, "subscription_expired", "TIME_ELAPSED"),
        (
            0,
            NOW + timedelta(days=10),
            "visits_exhausted",
            "VISITS_EXHAUSTED",
        ),
    ],
)
async def test_rejected_attendance_commits_expiration_and_system_audit(
    database_url: str,
    remaining_visits: int,
    expires_at: datetime,
    expected_code: str,
    reason: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context = await setup_context(
        session_factory,
        remaining_visits=remaining_visits,
        expires_at=expires_at,
    )
    try:
        response = await execute_api_confirmation(session_factory, context)

        assert response.status_code == 409
        assert json.loads(response.body)["code"] == expected_code
        async with session_factory() as verification:
            stored_subscription = await verification.get(
                SubscriptionModel,
                context.subscription_id,
            )
            attendance_count = await verification.scalar(
                select(func.count(AttendanceModel.id)).where(
                    AttendanceModel.athlete_id == context.athlete_id
                )
            )
            audits = (
                await verification.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.entity_type == "SUBSCRIPTION",
                        AuditLogModel.entity_id == context.subscription_id,
                    )
                )
            ).all()
            assert stored_subscription is not None
            assert stored_subscription.status is SubscriptionStatus.EXPIRED
            assert attendance_count == 0
            assert len(audits) == 1
            assert audits[0].action == "SUBSCRIPTION_EXPIRED"
            assert audits[0].actor_user_id is None
            assert audits[0].payload is not None
            assert audits[0].payload["reason"] == reason
    finally:
        await cleanup_context(session_factory, context)
        await engine.dispose()


async def test_last_visit_persists_attendance_expiration_and_two_audits(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context = await setup_context(session_factory, remaining_visits=1)
    try:
        outcome = await execute_confirmation(session_factory, context)

        assert outcome is ConfirmAttendanceOutcome.CONFIRMED
        async with session_factory() as verification:
            stored_subscription = await verification.get(
                SubscriptionModel,
                context.subscription_id,
            )
            attendance = await verification.scalar(
                select(AttendanceModel).where(
                    AttendanceModel.athlete_id == context.athlete_id
                )
            )
            assert attendance is not None
            audits = (
                await verification.scalars(
                    select(AuditLogModel)
                    .where(
                        or_(
                            and_(
                                AuditLogModel.entity_type == "ATTENDANCE",
                                AuditLogModel.entity_id == attendance.id,
                            ),
                            and_(
                                AuditLogModel.entity_type == "SUBSCRIPTION",
                                AuditLogModel.entity_id
                                == context.subscription_id,
                            ),
                        )
                    )
                    .order_by(AuditLogModel.id)
                )
            ).all()
            assert stored_subscription is not None
            assert stored_subscription.remaining_visits == 0
            assert stored_subscription.status is SubscriptionStatus.EXPIRED
            assert attendance.source is AttendanceSource.QR
            assert attendance.status is AttendanceStatus.CONFIRMED
            assert [audit.action for audit in audits] == [
                "ATTENDANCE_CREATED",
                "SUBSCRIPTION_EXPIRED",
            ]
    finally:
        await cleanup_context(session_factory, context)
        await engine.dispose()


async def test_two_concurrent_last_visit_scans_preserve_invariants(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context = await setup_context(session_factory, remaining_visits=1)
    try:
        outcomes = await asyncio.gather(
            execute_confirmation(session_factory, context),
            execute_confirmation(session_factory, context),
        )

        assert outcomes.count(ConfirmAttendanceOutcome.CONFIRMED) == 1
        assert outcomes.count(ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION) == 1
        async with session_factory() as verification:
            stored_subscription = await verification.get(
                SubscriptionModel,
                context.subscription_id,
            )
            attendances = (
                await verification.scalars(
                    select(AttendanceModel).where(
                        AttendanceModel.athlete_id == context.athlete_id
                    )
                )
            ).all()
            assert stored_subscription is not None
            assert stored_subscription.remaining_visits == 0
            assert stored_subscription.status is SubscriptionStatus.EXPIRED
            assert len(attendances) == 1
    finally:
        await cleanup_context(session_factory, context)
        await engine.dispose()


async def test_regular_session_projection_is_current_day_sorted_and_keeps_cancelled(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    context = await setup_context(session_factory)
    mini_group_id: int | None = None
    mini_group_name_id: int | None = None
    try:
        async with session_factory() as setup:
            cancelled = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=context.group_id,
                trainer_id=context.actor_id,
                starts_at=NOW - timedelta(hours=3),
                ends_at=NOW - timedelta(hours=2),
                status=TrainingSessionStatus.CANCELLED,
                is_overridden=False,
            )
            yesterday = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=context.group_id,
                trainer_id=context.actor_id,
                starts_at=NOW - timedelta(days=1),
                ends_at=NOW - timedelta(days=1) + timedelta(hours=1),
                status=TrainingSessionStatus.SCHEDULED,
                is_overridden=False,
            )
            mini_name = GroupNameModel(name=f"MINI ATT {uuid4().hex[:10]}")
            setup.add(mini_name)
            await setup.flush()
            mini_group = TrainingGroupModel(
                direction_id=context.direction_id,
                trainer_id=context.actor_id,
                name_id=mini_name.id,
                group_type=TrainingGroupType.MINI,
                is_active=True,
            )
            setup.add(mini_group)
            await setup.flush()
            mini_session = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=mini_group.id,
                trainer_id=context.actor_id,
                starts_at=NOW + timedelta(hours=2),
                ends_at=NOW + timedelta(hours=3),
                status=TrainingSessionStatus.SCHEDULED,
                is_overridden=False,
            )
            setup.add_all([cancelled, yesterday, mini_session])
            await setup.commit()
            mini_group_id = mini_group.id
            mini_group_name_id = mini_name.id

        async with session_factory() as session:
            items = await SqlAlchemyAttendanceSessionRepository(
                session
            ).list_regular(
                starts_at_from=datetime(2026, 8, 31, 21, tzinfo=UTC),
                starts_at_to=datetime(2026, 9, 1, 21, tzinfo=UTC),
            )

        scoped = [
            item for item in items if item.training_group_id == context.group_id
        ]
        assert [item.status for item in scoped] == [
            TrainingSessionStatus.CANCELLED,
            TrainingSessionStatus.SCHEDULED,
        ]
        assert [item.id for item in scoped] == [
            cancelled.id,
            context.training_session_id,
        ]
        assert all(
            item.training_group_id != mini_group_id for item in items
        )
    finally:
        if mini_group_id is not None and mini_group_name_id is not None:
            async with session_factory() as cleanup:
                await cleanup.execute(
                    delete(TrainingSessionModel).where(
                        TrainingSessionModel.group_id == mini_group_id
                    )
                )
                await cleanup.execute(
                    delete(TrainingGroupModel).where(
                        TrainingGroupModel.id == mini_group_id
                    )
                )
                await cleanup.execute(
                    delete(GroupNameModel).where(
                        GroupNameModel.id == mini_group_name_id
                    )
                )
                await cleanup.commit()
        await cleanup_context(session_factory, context)
        await engine.dispose()
