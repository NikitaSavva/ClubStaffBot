import asyncio
from datetime import UTC, datetime, time
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.club import (
    AssignTrainingGroupTrainerCommand,
    AssignTrainingGroupTrainerInteractor,
    AssignTrainingGroupTrainerResult,
)
from application.club.errors import TrainingGroupTrainerAlreadyAssignedError
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from infrastructure.database.models import (
    AuditLogModel,
    GroupNameModel,
    RoleModel,
    ScheduleRuleModel,
    SportDirectionModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.readers import (
    SqlAlchemyBotUserReader,
    SqlAlchemyTrainingGroupReader,
)
from infrastructure.database.repositories import (
    SqlAlchemyAuditLogRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyTrainingGroupRepository,
    SqlAlchemyUserRepository,
)
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.database.system_roles import ensure_system_roles
from infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


async def role_by_code(
    session: AsyncSession,
    code: SystemRoleCode,
) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(RoleModel.code == code.value)
    )
    assert role is not None
    return role


async def ensure_role(
    session: AsyncSession,
    code: SystemRoleCode,
) -> None:
    existing = await session.scalar(
        select(RoleModel).where(RoleModel.code == code.value)
    )
    if existing is None:
        session.add(
            RoleModel(
                code=code.value,
                name=code.value.title(),
                is_system=True,
                is_active=True,
            )
        )
        await session.flush()


async def add_user_with_role(
    session: AsyncSession,
    *,
    telegram_id: int,
    role_code: SystemRoleCode,
    first_name: str,
) -> UserModel:
    suffix = uuid4().hex[:8]
    user = UserModel(
        telegram_id=telegram_id,
        username=f"{first_name.lower()}_{suffix}",
        first_name=first_name,
        last_name=suffix,
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    role = await role_by_code(session, role_code)
    session.add(
        UserRoleModel(
            user_id=user.id,
            role_id=role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    return user


async def add_duplicate_name_groups(
    session: AsyncSession,
) -> tuple[TrainingGroupModel, TrainingGroupModel]:
    suffix = uuid4().hex[:8]
    direction = SportDirectionModel(
        code=f"TEST_{suffix}",
        name=f"Кикбоксинг {suffix}",
        is_active=True,
    )
    name = GroupNameModel(name=f"Взрослые {suffix}")
    session.add_all([direction, name])
    await session.flush()

    first = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=None,
        name_id=name.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    second = TrainingGroupModel(
        direction_id=direction.id,
        trainer_id=None,
        name_id=name.id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add_all([first, second])
    await session.flush()
    session.add_all(
        [
            ScheduleRuleModel(
                group_id=first.id,
                weekday=weekday,
                start_time=time(19, 0),
                end_time=time(20, 30),
                valid_from=None,
                valid_until=None,
                is_active=True,
            )
            for weekday in (0, 2, 4)
        ]
        + [
            ScheduleRuleModel(
                group_id=second.id,
                weekday=weekday,
                start_time=time(8, 30),
                end_time=time(10, 0),
                valid_from=None,
                valid_until=None,
                is_active=True,
            )
            for weekday in (1, 3, 5)
        ]
    )
    return first, second


async def execute_assignment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_telegram_id: int,
    training_group_id: int,
    trainer_user_id: int,
) -> AssignTrainingGroupTrainerResult:
    async with session_factory() as session:
        return await AssignTrainingGroupTrainerInteractor(
            user_repository=SqlAlchemyUserRepository(session),
            role_repository=SqlAlchemyRoleRepository(session),
            training_group_repository=SqlAlchemyTrainingGroupRepository(
                session
            ),
            audit_log_repository=SqlAlchemyAuditLogRepository(session),
            unit_of_work=SqlAlchemyUnitOfWork(session),
        )(
            AssignTrainingGroupTrainerCommand(
                actor_telegram_id=actor_telegram_id,
                training_group_id=training_group_id,
                trainer_user_id=trainer_user_id,
            )
        )


async def test_reader_returns_duplicate_names_with_actual_schedule_rules(
    db_session: AsyncSession,
) -> None:
    first, second = await add_duplicate_name_groups(db_session)
    await db_session.flush()

    summaries = await SqlAlchemyTrainingGroupReader(db_session).list_all()
    selected = {
        summary.training_group_id: summary
        for summary in summaries
        if summary.training_group_id in {first.id, second.id}
    }

    assert set(selected) == {first.id, second.id}
    assert selected[first.id].group_name == selected[second.id].group_name
    assert selected[first.id].schedule_rules != selected[second.id].schedule_rules
    assert [rule.weekday for rule in selected[first.id].schedule_rules] == [
        0,
        2,
        4,
    ]
    assert [rule.weekday for rule in selected[second.id].schedule_rules] == [
        1,
        3,
        5,
    ]
    assert first.name_id == second.name_id


async def test_trainer_reader_returns_only_users_with_active_trainer_role(
    db_session: AsyncSession,
) -> None:
    trainer_telegram_id = 61_000_000 + uuid4().int % 1_000_000_000
    athlete_telegram_id = 62_000_000 + uuid4().int % 1_000_000_000
    await ensure_role(db_session, SystemRoleCode.TRAINER)
    await ensure_role(db_session, SystemRoleCode.ATHLETE)
    trainer = await add_user_with_role(
        db_session,
        telegram_id=trainer_telegram_id,
        role_code=SystemRoleCode.TRAINER,
        first_name="Trainer",
    )
    athlete = await add_user_with_role(
        db_session,
        telegram_id=athlete_telegram_id,
        role_code=SystemRoleCode.ATHLETE,
        first_name="Athlete",
    )

    trainers = await SqlAlchemyBotUserReader(db_session).list_by_role(
        SystemRoleCode.TRAINER
    )

    trainer_ids = {candidate.user_id for candidate in trainers}
    assert trainer.id in trainer_ids
    assert athlete.id not in trainer_ids


async def test_concurrent_assignments_lock_group_and_create_one_audit(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    actor_telegram_id = 63_000_000 + uuid4().int % 1_000_000_000
    first_trainer_telegram_id = 64_000_000 + uuid4().int % 1_000_000_000
    second_trainer_telegram_id = 65_000_000 + uuid4().int % 1_000_000_000
    created_group_ids: tuple[int, int] | None = None
    created_user_ids: tuple[int, int, int] | None = None
    created_direction_id: int | None = None
    created_name_id: int | None = None
    try:
        await ensure_system_roles(session_factory)
        async with session_factory.begin() as session:
            actor = await add_user_with_role(
                session,
                telegram_id=actor_telegram_id,
                role_code=SystemRoleCode.ADMINISTRATOR,
                first_name="Admin",
            )
            first_trainer = await add_user_with_role(
                session,
                telegram_id=first_trainer_telegram_id,
                role_code=SystemRoleCode.TRAINER,
                first_name="First",
            )
            second_trainer = await add_user_with_role(
                session,
                telegram_id=second_trainer_telegram_id,
                role_code=SystemRoleCode.TRAINER,
                first_name="Second",
            )
            group, other_group = await add_duplicate_name_groups(session)
            group_id = group.id
            created_group_ids = (group.id, other_group.id)
            created_user_ids = (
                actor.id,
                first_trainer.id,
                second_trainer.id,
            )
            created_direction_id = group.direction_id
            created_name_id = group.name_id

        outcomes = await asyncio.gather(
            execute_assignment(
                session_factory,
                actor_telegram_id=actor_telegram_id,
                training_group_id=group_id,
                trainer_user_id=first_trainer.id,
            ),
            execute_assignment(
                session_factory,
                actor_telegram_id=actor_telegram_id,
                training_group_id=group_id,
                trainer_user_id=second_trainer.id,
            ),
            return_exceptions=True,
        )

        assert sum(
            isinstance(outcome, AssignTrainingGroupTrainerResult)
            for outcome in outcomes
        ) == 1
        assert sum(
            isinstance(
                outcome,
                TrainingGroupTrainerAlreadyAssignedError,
            )
            for outcome in outcomes
        ) == 1

        async with session_factory() as session:
            persisted_trainer_id = await session.scalar(
                select(TrainingGroupModel.trainer_id).where(
                    TrainingGroupModel.id == group_id
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "TRAINER_ASSIGNED",
                    AuditLogModel.entity_type == "TRAINING_GROUP",
                    AuditLogModel.entity_id == group_id,
                )
            )

        assert persisted_trainer_id in {
            first_trainer.id,
            second_trainer.id,
        }
        assert audit_count == 1
    finally:
        if created_group_ids is not None and created_user_ids is not None:
            async with session_factory.begin() as session:
                await session.execute(
                    delete(AuditLogModel).where(
                        AuditLogModel.entity_type == "TRAINING_GROUP",
                        AuditLogModel.entity_id.in_(created_group_ids),
                    )
                )
                await session.execute(
                    delete(ScheduleRuleModel).where(
                        ScheduleRuleModel.group_id.in_(created_group_ids)
                    )
                )
                await session.execute(
                    delete(TrainingGroupModel).where(
                        TrainingGroupModel.id.in_(created_group_ids)
                    )
                )
                await session.execute(
                    delete(UserRoleModel).where(
                        UserRoleModel.user_id.in_(created_user_ids)
                    )
                )
                await session.execute(
                    delete(UserModel).where(UserModel.id.in_(created_user_ids))
                )
                if created_name_id is not None:
                    await session.execute(
                        delete(GroupNameModel).where(
                            GroupNameModel.id == created_name_id
                        )
                    )
                if created_direction_id is not None:
                    await session.execute(
                        delete(SportDirectionModel).where(
                            SportDirectionModel.id == created_direction_id
                        )
                    )
        await engine.dispose()
