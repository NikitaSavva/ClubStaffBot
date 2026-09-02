from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    EditMessageCaption,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.attendance import AttendanceSource
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionAccessScope, SubscriptionStatus
from entrypoints.bot import create_dispatcher
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
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
)
from presentation.telegram.handlers.manual_attendance import (
    MANUAL_ATTENDANCE_ACTION,
    ManualAttendanceAction,
    ManualAttendanceCallback,
)
from tests.functional.telegram.fakes import telegram_method_result

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


@dataclass(frozen=True, slots=True)
class FlowData:
    actor: User
    actor_user_id: int
    athlete_id: int
    athlete_public_id: str
    plan_id: int
    direction_id: int
    group_ids: tuple[int, ...]
    group_name_ids: tuple[int, ...]
    subscription_id: int
    scheduled_session_id: int
    cancelled_session_id: int | None
    mini_session_id: int | None


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup


def callback_update(
    *,
    update_id: int,
    sender: User,
    data: str,
    message_id: int,
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"manual-callback-{update_id}",
            from_user=sender,
            chat_instance=f"manual-chat-{sender.id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=datetime.now(UTC),
                chat=Chat(id=sender.id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                text="Manual attendance",
            ),
        ),
    )


def command_update(*, update_id: int, sender: User, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=sender.id, type=ChatType.PRIVATE),
            from_user=sender,
            text=text,
        ),
    )


def last_screen(methods: list[TelegramMethod[Any]]) -> ScreenSnapshot:
    for method in reversed(methods):
        if isinstance(method, SendPhoto):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, EditMessageCaption):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, (SendMessage, EditMessageText)):
            text = method.text
            reply_markup = method.reply_markup
        else:
            continue
        if text is not None and isinstance(reply_markup, InlineKeyboardMarkup):
            return ScreenSnapshot(text=text, reply_markup=reply_markup)
    raise AssertionError("No rendered screen with keyboard")


def callback_texts(screen: ScreenSnapshot) -> dict[str, str]:
    return {
        button.callback_data: button.text
        for row in screen.reply_markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def sent_message_id(
    methods: list[TelegramMethod[Any]],
    target: TelegramMethod[Any],
) -> int:
    return next(
        index
        for index, method in enumerate(methods, start=1)
        if method is target
    )


async def arrange_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    unlimited: bool,
) -> FlowData:
    suffix = uuid4().hex[:10]
    actor_telegram_id = 81_000_000 + uuid4().int % 1_000_000_000
    actor_sender = User(
        id=actor_telegram_id,
        is_bot=False,
        first_name="Admin",
        last_name="User",
        username=f"manual_admin_{suffix}",
    )
    local_date = datetime.now(CLUB_TIMEZONE).date()
    session_start = datetime.combine(
        local_date,
        time(12),
        tzinfo=CLUB_TIMEZONE,
    ).astimezone(UTC)
    now = datetime.now(UTC)
    async with session_factory.begin() as session:
        role = await session.scalar(
            select(RoleModel).where(
                RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
            )
        )
        assert role is not None
        actor = UserModel(
            telegram_id=actor_telegram_id,
            username=actor_sender.username,
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=now,
            last_seen_at=now,
        )
        athlete = AthleteModel(
            user_id=None,
            first_name="Иван",
            last_name=f"Иванов{suffix}",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        direction = SportDirectionModel(
            code=f"MANUAL_{suffix}",
            name="Кикбоксинг",
            short_name="K1",
            is_active=True,
        )
        plan = SubscriptionPlanModel(
            code=f"MANUAL_PLAN_{suffix}",
            name="Безлимит" if unlimited else "8 посещений",
            visit_limit=None if unlimited else 8,
            duration_months=1,
            price=Decimal("10000" if unlimited else "4000"),
            is_unlimited=unlimited,
            access_scope=(
                SubscriptionAccessScope.ALL_REGULAR_GROUPS
                if unlimited
                else SubscriptionAccessScope.SPECIFIC_GROUP
            ),
            required_group_type=(
                None if unlimited else TrainingGroupType.REGULAR
            ),
            is_active=True,
        )
        session.add_all([actor, athlete, direction, plan])
        await session.flush()
        session.add(
            UserRoleModel(
                user_id=actor.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=now,
            )
        )
        regular_name = GroupNameModel(name=f"Взрослые {suffix}")
        session.add(regular_name)
        await session.flush()
        regular_group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=actor.id,
            name_id=regular_name.id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        session.add(regular_group)
        await session.flush()
        subscription = SubscriptionModel(
            athlete_id=athlete.id,
            group_id=None if unlimited else regular_group.id,
            plan_id=plan.id,
            activated_by_user_id=actor.id,
            activated_at=now - timedelta(days=1),
            starts_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=20),
            activation_price=plan.price,
            remaining_visits=None if unlimited else 8,
            status=SubscriptionStatus.ACTIVE,
        )
        scheduled = TrainingSessionModel(
            schedule_rule_id=None,
            group_id=regular_group.id,
            trainer_id=actor.id,
            starts_at=session_start,
            ends_at=session_start + timedelta(hours=1),
            status=TrainingSessionStatus.SCHEDULED,
            is_overridden=False,
        )
        session.add_all([subscription, scheduled])
        await session.flush()
        group_ids = [regular_group.id]
        group_name_ids = [regular_name.id]
        cancelled_id: int | None = None
        mini_id: int | None = None
        if unlimited:
            cancelled = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=regular_group.id,
                trainer_id=actor.id,
                starts_at=session_start + timedelta(hours=2),
                ends_at=session_start + timedelta(hours=3),
                status=TrainingSessionStatus.CANCELLED,
                is_overridden=False,
            )
            mini_name = GroupNameModel(name=f"Мини {suffix}")
            session.add_all([cancelled, mini_name])
            await session.flush()
            mini_group = TrainingGroupModel(
                direction_id=direction.id,
                trainer_id=actor.id,
                name_id=mini_name.id,
                group_type=TrainingGroupType.MINI,
                is_active=True,
            )
            session.add(mini_group)
            await session.flush()
            mini = TrainingSessionModel(
                schedule_rule_id=None,
                group_id=mini_group.id,
                trainer_id=actor.id,
                starts_at=session_start + timedelta(hours=4),
                ends_at=session_start + timedelta(hours=5),
                status=TrainingSessionStatus.SCHEDULED,
                is_overridden=False,
            )
            session.add(mini)
            await session.flush()
            group_ids.append(mini_group.id)
            group_name_ids.append(mini_name.id)
            cancelled_id = cancelled.id
            mini_id = mini.id
        return FlowData(
            actor=actor_sender,
            actor_user_id=actor.id,
            athlete_id=athlete.id,
            athlete_public_id=str(athlete.athlete_public_id),
            plan_id=plan.id,
            direction_id=direction.id,
            group_ids=tuple(group_ids),
            group_name_ids=tuple(group_name_ids),
            subscription_id=subscription.id,
            scheduled_session_id=scheduled.id,
            cancelled_session_id=cancelled_id,
            mini_session_id=mini_id,
        )


async def cleanup_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    async with session_factory.begin() as session:
        attendance_ids = tuple(
            await session.scalars(
                select(AttendanceModel.id).where(
                    AttendanceModel.athlete_id == data.athlete_id
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
                AuditLogModel.entity_id == data.subscription_id,
            )
        )
        await session.execute(
            delete(AttendanceModel).where(
                AttendanceModel.athlete_id == data.athlete_id
            )
        )
        await session.execute(
            delete(TrainingSessionModel).where(
                TrainingSessionModel.group_id.in_(data.group_ids)
            )
        )
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.id == data.subscription_id
            )
        )
        await session.execute(
            delete(UserRoleModel).where(
                UserRoleModel.user_id == data.actor_user_id
            )
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id.in_(data.group_ids)
            )
        )
        await session.execute(
            delete(GroupNameModel).where(
                GroupNameModel.id.in_(data.group_name_ids)
            )
        )
        await session.execute(
            delete(SubscriptionPlanModel).where(
                SubscriptionPlanModel.id == data.plan_id
            )
        )
        await session.execute(
            delete(SportDirectionModel).where(
                SportDirectionModel.id == data.direction_id
            )
        )
        await session.execute(
            delete(AthleteModel).where(AthleteModel.id == data.athlete_id)
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == data.actor_user_id)
        )


async def open_manual_selector(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
) -> int:
    await dispatcher.feed_update(
        bot,
        command_update(update_id=1, sender=data.actor, text="/menu"),
    )
    menu_method = next(method for method in methods if isinstance(method, SendPhoto))
    menu_id = sent_message_id(methods, menu_method)
    assert callback_texts(last_screen(methods))[MANUAL_ATTENDANCE_ACTION] == (
        "Отметить вход"
    )
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=2,
            sender=data.actor,
            data=MANUAL_ATTENDANCE_ACTION,
            message_id=menu_id,
        ),
    )
    selector_method = next(
        method for method in methods if isinstance(method, SendMessage)
    )
    return sent_message_id(methods, selector_method)


async def test_specific_group_manual_athlete_persists_manual_source(
    integration_settings: Settings,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    session_factory: async_sessionmaker[AsyncSession] | None = None
    data: FlowData | None = None
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        data = await arrange_flow_data(session_factory, unlimited=False)
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        selector_id = await open_manual_selector(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
        )
        select_athlete = AthleteSelectorCallback(
            purpose=AthleteSelectionPurpose.ATTENDANCE,
            action=AthleteSelectorAction.SELECT,
            value=data.athlete_public_id,
        ).pack()
        assert select_athlete in callback_texts(last_screen(methods))

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.actor,
                data=select_athlete,
                message_id=selector_id,
            ),
        )

        assert last_screen(methods).text.startswith("Посещение отмечено")
        async with session_factory() as verification:
            athlete = await verification.get(AthleteModel, data.athlete_id)
            attendance = await verification.scalar(
                select(AttendanceModel).where(
                    AttendanceModel.athlete_id == data.athlete_id
                )
            )
            assert athlete is not None and athlete.user_id is None
            assert attendance is not None
            assert attendance.source is AttendanceSource.MANUAL
            assert attendance.confirmed_by_user_id == data.actor_user_id
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_unlimited_uses_session_selector_and_explicit_confirmation(
    integration_settings: Settings,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    session_factory: async_sessionmaker[AsyncSession] | None = None
    data: FlowData | None = None
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        data = await arrange_flow_data(session_factory, unlimited=True)
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        selector_id = await open_manual_selector(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.actor,
                data=AthleteSelectorCallback(
                    purpose=AthleteSelectionPurpose.ATTENDANCE,
                    action=AthleteSelectorAction.SELECT,
                    value=data.athlete_public_id,
                ).pack(),
                message_id=selector_id,
            ),
        )

        session_screen = last_screen(methods)
        callbacks = callback_texts(session_screen)
        assert session_screen.text.startswith("Выберите тренировку")
        assert ManualAttendanceCallback(
            action=ManualAttendanceAction.SESSION,
            value=data.scheduled_session_id,
        ).pack() in callbacks
        assert data.cancelled_session_id is not None
        cancelled_callback = ManualAttendanceCallback(
            action=ManualAttendanceAction.CANCELLED,
            value=data.cancelled_session_id,
        ).pack()
        assert callbacks[cancelled_callback].endswith("— Отменена")
        assert data.mini_session_id is not None
        assert ManualAttendanceCallback(
            action=ManualAttendanceAction.SESSION,
            value=data.mini_session_id,
        ).pack() not in callbacks

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=data.actor,
                data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.SESSION,
                    value=data.scheduled_session_id,
                ).pack(),
                message_id=selector_id,
            ),
        )
        confirmation = last_screen(methods)
        assert confirmation.text.startswith("Отметить посещение?")
        async with session_factory() as verification:
            assert await verification.scalar(
                select(AttendanceModel).where(
                    AttendanceModel.athlete_id == data.athlete_id
                )
            ) is None

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.actor,
                data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.CONFIRM,
                    value=0,
                ).pack(),
                message_id=selector_id,
            ),
        )

        assert last_screen(methods).text.startswith("Посещение отмечено")
        async with session_factory() as verification:
            attendance = await verification.scalar(
                select(AttendanceModel).where(
                    AttendanceModel.athlete_id == data.athlete_id
                )
            )
            assert attendance is not None
            assert attendance.source is AttendanceSource.MANUAL
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()
