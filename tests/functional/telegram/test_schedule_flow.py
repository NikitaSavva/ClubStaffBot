from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    AnswerCallbackQuery,
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
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionStatus
from entrypoints.bot import create_dispatcher
from infrastructure.clock import SystemClock
from infrastructure.database.models import (
    AthleteModel,
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
from presentation.telegram.handlers.schedules import (
    ADMINISTRATIVE_SCHEDULE_ACTION,
    ATHLETE_SCHEDULE_ACTION,
    TRAINER_SCHEDULE_ACTION,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import RolePanel, RolePanelCallback
from presentation.telegram.presenters.schedules import (
    NO_ACTIVE_SUBSCRIPTION_TEXT,
)
from tests.functional.telegram.fakes import telegram_method_result

CLUB_TIMEZONE = ZoneInfo("Europe/Moscow")
NOW_LOCAL = datetime(2026, 8, 31, 12, tzinfo=CLUB_TIMEZONE)
NOW = NOW_LOCAL.astimezone(UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


@dataclass(frozen=True, slots=True)
class FlowData:
    telegram_user: User
    user_id: int
    athlete_id: int
    subscription_id: int | None
    group_ids: tuple[int, ...]
    group_name_ids: tuple[int, ...]
    direction_id: int
    other_user_id: int
    own_group_name: str
    other_group_name: str
    mini_group_name: str


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup
    method: TelegramMethod[Any]


def command_update(*, update_id: int, sender: User, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=NOW,
            chat=Chat(id=sender.id, type=ChatType.PRIVATE),
            from_user=sender,
            text=text,
        ),
    )


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
            id=f"callback-{update_id}",
            from_user=sender,
            chat_instance=f"chat-{sender.id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=NOW,
                chat=Chat(id=sender.id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                caption="UI screen",
            ),
        ),
    )


def last_screen(methods: list[TelegramMethod[Any]]) -> ScreenSnapshot:
    for method in reversed(methods):
        if isinstance(method, SendPhoto):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, SendMessage):
            text = method.text
            reply_markup = method.reply_markup
        else:
            continue
        if text is not None and isinstance(reply_markup, InlineKeyboardMarkup):
            return ScreenSnapshot(text, reply_markup, method)
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


async def get_role(
    session: AsyncSession,
    code: SystemRoleCode,
) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(RoleModel.code == code.value)
    )
    assert role is not None
    return role


async def arrange_flow(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    service_role: SystemRoleCode,
    with_subscription: bool = True,
) -> FlowData:
    suffix = uuid4().hex[:8]
    telegram_id = 9_000_000_000 + uuid4().int % 500_000_000
    telegram_user = User(
        id=telegram_id,
        is_bot=False,
        first_name="Иван",
        last_name="Иванов",
        username=f"schedule_{suffix}",
    )
    async with session_factory.begin() as session:
        actor = UserModel(
            telegram_id=telegram_id,
            username=telegram_user.username,
            first_name="Иван",
            last_name="Иванов",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        other = UserModel(
            telegram_id=telegram_id + 1,
            username=f"other_{suffix}",
            first_name="Другой",
            last_name="Тренер",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add_all((actor, other))
        await session.flush()
        for role_code in (SystemRoleCode.ATHLETE, service_role):
            role = await get_role(session, role_code)
            session.add(
                UserRoleModel(
                    user_id=actor.id,
                    role_id=role.id,
                    assigned_by_user_id=None,
                    assigned_at=NOW,
                )
            )

        athlete = AthleteModel(
            user_id=actor.id,
            first_name="Иван",
            last_name="Иванов",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        direction = SportDirectionModel(
            code=f"FLOW_{suffix}",
            name=f"Направление {suffix}",
            short_name=None,
            is_active=True,
        )
        names = tuple(
            GroupNameModel(name=f"{label} {suffix}")
            for label in ("Своя", "Другая", "Мини")
        )
        session.add_all((athlete, direction, *names))
        await session.flush()

        own_group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=other.id,
            name_id=names[0].id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        other_group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=other.id,
            name_id=names[1].id,
            group_type=TrainingGroupType.REGULAR,
            is_active=True,
        )
        mini_group = TrainingGroupModel(
            direction_id=direction.id,
            trainer_id=other.id,
            name_id=names[2].id,
            group_type=TrainingGroupType.MINI,
            is_active=True,
        )
        session.add_all((own_group, other_group, mini_group))
        await session.flush()

        service_trainer_id = (
            actor.id if service_role is SystemRoleCode.TRAINER else other.id
        )
        session.add_all(
            (
                TrainingSessionModel(
                    schedule_rule_id=None,
                    group_id=own_group.id,
                    trainer_id=other.id,
                    starts_at=NOW_LOCAL.replace(hour=9),
                    ends_at=NOW_LOCAL.replace(hour=10, minute=30),
                    status=TrainingSessionStatus.CANCELLED,
                    is_overridden=False,
                ),
                TrainingSessionModel(
                    schedule_rule_id=None,
                    group_id=other_group.id,
                    trainer_id=service_trainer_id,
                    starts_at=NOW_LOCAL.replace(hour=12),
                    ends_at=NOW_LOCAL.replace(hour=13, minute=30),
                    status=TrainingSessionStatus.SCHEDULED,
                    is_overridden=False,
                ),
                TrainingSessionModel(
                    schedule_rule_id=None,
                    group_id=mini_group.id,
                    trainer_id=other.id,
                    starts_at=NOW_LOCAL.replace(hour=14),
                    ends_at=NOW_LOCAL.replace(hour=15, minute=30),
                    status=TrainingSessionStatus.SCHEDULED,
                    is_overridden=False,
                ),
            )
        )

        subscription_id: int | None = None
        if with_subscription:
            plan = await session.scalar(
                select(SubscriptionPlanModel).where(
                    SubscriptionPlanModel.code == "12_VISITS"
                )
            )
            assert plan is not None
            subscription = SubscriptionModel(
                athlete_id=athlete.id,
                group_id=own_group.id,
                plan_id=plan.id,
                activated_by_user_id=actor.id,
                activated_at=NOW - timedelta(days=1),
                starts_at=NOW - timedelta(days=1),
                expires_at=NOW + timedelta(days=30),
                activation_price=Decimal(plan.price),
                remaining_visits=0,
                status=SubscriptionStatus.ACTIVE,
            )
            session.add(subscription)
            await session.flush()
            subscription_id = subscription.id

        return FlowData(
            telegram_user=telegram_user,
            user_id=actor.id,
            athlete_id=athlete.id,
            subscription_id=subscription_id,
            group_ids=(own_group.id, other_group.id, mini_group.id),
            group_name_ids=tuple(item.id for item in names),
            direction_id=direction.id,
            other_user_id=other.id,
            own_group_name=names[0].name,
            other_group_name=names[1].name,
            mini_group_name=names[2].name,
        )


async def cleanup_flow(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            delete(TrainingSessionModel).where(
                TrainingSessionModel.group_id.in_(data.group_ids)
            )
        )
        if data.subscription_id is not None:
            await session.execute(
                delete(SubscriptionModel).where(
                    SubscriptionModel.id == data.subscription_id
                )
            )
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id == data.user_id)
        )
        await session.execute(
            delete(AthleteModel).where(AthleteModel.id == data.athlete_id)
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
            delete(SportDirectionModel).where(
                SportDirectionModel.id == data.direction_id
            )
        )
        await session.execute(
            delete(UserModel).where(
                UserModel.id.in_((data.user_id, data.other_user_id))
            )
        )


async def select_role(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
    role: RolePanel,
    update_id: int,
) -> int:
    selector = last_screen(methods)
    selector_id = sent_message_id(methods, selector.method)
    callback_data = RolePanelCallback(role=role).pack()
    assert callback_data in callback_texts(selector)
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=update_id,
            sender=data.telegram_user,
            data=callback_data,
            message_id=selector_id,
        ),
    )
    panel = last_screen(methods)
    return sent_message_id(methods, panel.method)


@pytest.mark.parametrize(
    ("service_role", "service_panel", "service_action"),
    [
        (
            SystemRoleCode.TRAINER,
            RolePanel.TRAINER,
            TRAINER_SCHEDULE_ACTION,
        ),
        (
            SystemRoleCode.OWNER,
            RolePanel.OWNER,
            ADMINISTRATIVE_SCHEDULE_ACTION,
        ),
    ],
)
async def test_multi_role_schedule_scopes_and_navigation(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    service_role: SystemRoleCode,
    service_panel: RolePanel,
    service_action: str,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    data: FlowData | None = None

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    monkeypatch.setattr(SystemClock, "now", lambda _self: NOW)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(
            session_factory,
            service_role=service_role,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)

        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=1,
                sender=data.telegram_user,
                text="/menu",
            ),
        )
        athlete_panel_id = await select_role(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            role=RolePanel.ATHLETE,
            update_id=2,
        )
        assert callback_texts(last_screen(methods))[
            ATHLETE_SCHEDULE_ACTION
        ] == "Расписание"
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.telegram_user,
                data=ATHLETE_SCHEDULE_ACTION,
                message_id=athlete_panel_id,
            ),
        )
        athlete_schedule = last_screen(methods)
        athlete_schedule_id = sent_message_id(methods, athlete_schedule.method)
        assert isinstance(athlete_schedule.method, SendMessage)
        assert data.own_group_name in athlete_schedule.text
        assert data.other_group_name not in athlete_schedule.text
        assert data.mini_group_name not in athlete_schedule.text
        assert "ОТМЕНЕНА" in athlete_schedule.text

        stale_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=data.telegram_user,
                data=ATHLETE_SCHEDULE_ACTION,
                message_id=athlete_panel_id,
            ),
        )
        stale_methods = methods[stale_offset:]
        assert len(stale_methods) == 1
        assert isinstance(stale_methods[0], AnswerCallbackQuery)
        assert stale_methods[0].text == STALE_SCREEN_TEXT

        back_to_panel = NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.telegram_user,
                data=back_to_panel,
                message_id=athlete_schedule_id,
            ),
        )
        athlete_panel = last_screen(methods)
        assert ATHLETE_SCHEDULE_ACTION in callback_texts(athlete_panel)

        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=6,
                sender=data.telegram_user,
                text="/menu",
            ),
        )
        service_panel_id = await select_role(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            role=service_panel,
            update_id=7,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=8,
                sender=data.telegram_user,
                data=service_action,
                message_id=service_panel_id,
            ),
        )
        service_schedule = last_screen(methods)
        assert isinstance(service_schedule.method, SendMessage)
        assert data.other_group_name in service_schedule.text
        if service_role is SystemRoleCode.TRAINER:
            assert data.own_group_name not in service_schedule.text
            assert data.mini_group_name not in service_schedule.text
        else:
            assert data.own_group_name in service_schedule.text
            assert data.mini_group_name in service_schedule.text

        acknowledgements = [
            method
            for method in methods
            if isinstance(method, AnswerCallbackQuery)
        ]
        assert len(acknowledgements) == 6
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()


async def test_athlete_without_subscription_gets_normal_state(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    data: FlowData | None = None

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    monkeypatch.setattr(SystemClock, "now", lambda _self: NOW)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(
            session_factory,
            service_role=SystemRoleCode.TRAINER,
            with_subscription=False,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=1,
                sender=data.telegram_user,
                text="/menu",
            ),
        )
        athlete_panel_id = await select_role(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            role=RolePanel.ATHLETE,
            update_id=2,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.telegram_user,
                data=ATHLETE_SCHEDULE_ACTION,
                message_id=athlete_panel_id,
            ),
        )

        assert NO_ACTIVE_SUBSCRIPTION_TEXT in last_screen(methods).text
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()
