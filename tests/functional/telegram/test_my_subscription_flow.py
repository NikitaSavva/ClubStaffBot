from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

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
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionStatus
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AthleteModel,
    RoleModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.my_subscription import (
    MY_SUBSCRIPTION_ACTION,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import RolePanel, RolePanelCallback
from presentation.telegram.presenters.subscriptions import (
    ATHLETE_PROFILE_NOT_FOUND_TEXT,
    NO_ACTIVE_SUBSCRIPTION_TEXT,
)
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 31, 10, tzinfo=UTC)
STARTS_AT = datetime(2026, 1, 1, 12, tzinfo=UTC)
EXPIRES_AT = datetime(2027, 1, 1, 12, tzinfo=UTC)
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
    athlete_id: int | None
    subscription_id: int | None


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup


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
    variant: str,
    roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.ATHLETE,),
) -> FlowData:
    telegram_id = 90_000_000 + uuid4().int % 1_000_000_000
    telegram_user = User(
        id=telegram_id,
        is_bot=False,
        first_name="Иван",
        last_name="Иванов",
        username=f"athlete_{uuid4().hex[:8]}",
    )
    async with session_factory.begin() as session:
        user = UserModel(
            telegram_id=telegram_id,
            username=telegram_user.username,
            first_name="Иван",
            last_name="Иванов",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(user)
        await session.flush()
        for code in roles:
            role = await get_role(session, code)
            session.add(
                UserRoleModel(
                    user_id=user.id,
                    role_id=role.id,
                    assigned_by_user_id=None,
                    assigned_at=NOW,
                )
            )

        if variant == "missing_profile":
            return FlowData(telegram_user, user.id, None, None)

        athlete = AthleteModel(
            user_id=user.id,
            first_name="Иван",
            last_name="Иванов",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        session.add(athlete)
        await session.flush()
        if variant == "no_active":
            return FlowData(telegram_user, user.id, athlete.id, None)

        plan_code = {
            "unlimited": "UNLIMITED",
            "mini": "MINI_GROUP",
        }.get(variant, "12_VISITS")
        plan = await session.scalar(
            select(SubscriptionPlanModel).where(
                SubscriptionPlanModel.code == plan_code
            )
        )
        assert plan is not None
        group_id: int | None = None
        if variant != "unlimited":
            group_type = (
                TrainingGroupType.MINI
                if variant == "mini"
                else TrainingGroupType.REGULAR
            )
            group_id = await session.scalar(
                select(TrainingGroupModel.id)
                .where(TrainingGroupModel.group_type == group_type)
                .order_by(TrainingGroupModel.id)
            )
            assert group_id is not None
        expires_at = (
            datetime(2025, 1, 1, 12, tzinfo=UTC)
            if variant == "expired"
            else EXPIRES_AT
        )
        starts_at = (
            datetime(2024, 12, 1, 12, tzinfo=UTC)
            if variant == "expired"
            else STARTS_AT
        )
        remaining_visits = (
            None
            if variant == "unlimited"
            else 0
            if variant == "zero"
            else 5
            if variant == "mini"
            else 7
        )
        subscription = SubscriptionModel(
            athlete_id=athlete.id,
            group_id=group_id,
            plan_id=plan.id,
            activated_by_user_id=user.id,
            activated_at=starts_at,
            starts_at=starts_at,
            expires_at=expires_at,
            activation_price=Decimal(plan.price),
            remaining_visits=remaining_visits,
            status=SubscriptionStatus.ACTIVE,
        )
        session.add(subscription)
        await session.flush()
        return FlowData(
            telegram_user,
            user.id,
            athlete.id,
            subscription.id,
        )


async def cleanup_flow(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    async with session_factory.begin() as session:
        if data.athlete_id is not None:
            await session.execute(
                delete(SubscriptionModel).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id == data.user_id)
        )
        if data.athlete_id is not None:
            await session.execute(
                delete(AthleteModel).where(
                    AthleteModel.id == data.athlete_id
                )
            )
        await session.execute(
            delete(UserModel).where(UserModel.id == data.user_id)
        )


async def open_athlete_home(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
    multi_role: bool,
) -> int:
    await dispatcher.feed_update(
        bot,
        command_update(update_id=1, sender=data.telegram_user, text="/menu"),
    )
    root = next(method for method in methods if isinstance(method, SendPhoto))
    root_id = sent_message_id(methods, root)
    if not multi_role:
        assert callback_texts(last_screen(methods))[MY_SUBSCRIPTION_ACTION] == (
            "Мой абонемент"
        )
        return root_id

    athlete_callback = RolePanelCallback(role=RolePanel.ATHLETE).pack()
    assert athlete_callback in callback_texts(last_screen(methods))
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=2,
            sender=data.telegram_user,
            data=athlete_callback,
            message_id=root_id,
        ),
    )
    athlete_home = next(
        method
        for method in reversed(methods)
        if isinstance(method, SendPhoto)
    )
    assert callback_texts(last_screen(methods))[MY_SUBSCRIPTION_ACTION] == (
        "Мой абонемент"
    )
    return sent_message_id(methods, athlete_home)


@pytest.mark.parametrize(
    ("variant", "expected_parts", "excluded_parts"),
    [
        (
            "limited",
            (
                "Тариф:\n12 посещений",
                "Группа:\nКикбоксинг · Сборная",
                "Осталось посещений:\n7",
            ),
            ("ПН", "Без ограничений"),
        ),
        (
            "mini",
            (
                "Тариф:\nМини-группа",
                "Группа:\nКикбоксинг · Мини-группа",
                "Осталось посещений:\n5",
            ),
            ("ПН", "Все обычные группы клуба"),
        ),
        (
            "unlimited",
            (
                "Тариф:\nБезлимит",
                "Доступ:\nВсе обычные группы клуба",
                "Мини-группы:\nНе входят",
                "Посещения:\nБез ограничений",
            ),
            ("Осталось посещений",),
        ),
        (
            "zero",
            ("Осталось посещений:\n0",),
            ("Без ограничений",),
        ),
        (
            "no_active",
            (NO_ACTIVE_SUBSCRIPTION_TEXT,),
            ("Тариф:", "Группа:"),
        ),
        (
            "expired",
            (NO_ACTIVE_SUBSCRIPTION_TEXT,),
            ("Тариф:", "Группа:"),
        ),
    ],
)
async def test_my_subscription_screen_variants(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    expected_parts: tuple[str, ...],
    excluded_parts: tuple[str, ...],
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
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(session_factory, variant=variant)
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=False,
        )

        offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.telegram_user,
                data=MY_SUBSCRIPTION_ACTION,
                message_id=home_id,
            ),
        )
        new_methods = methods[offset:]
        assert sum(
            isinstance(method, AnswerCallbackQuery)
            for method in new_methods
        ) == 1
        assert sum(isinstance(method, SendPhoto) for method in new_methods) == 1
        screen = last_screen(methods)
        assert screen.text.startswith("Мой абонемент")
        assert all(part in screen.text for part in expected_parts)
        assert all(part not in screen.text for part in excluded_parts)

        if variant == "expired":
            async with session_factory() as verification:
                status = await verification.scalar(
                    select(SubscriptionModel.status).where(
                        SubscriptionModel.id == data.subscription_id
                    )
                )
                assert status is SubscriptionStatus.ACTIVE
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()


async def test_missing_profile_is_controlled(
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
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(session_factory, variant="missing_profile")
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=False,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.telegram_user,
                data=MY_SUBSCRIPTION_ACTION,
                message_id=home_id,
            ),
        )

        assert ATHLETE_PROFILE_NOT_FOUND_TEXT in last_screen(methods).text
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()


async def test_multi_role_return_and_stale_home_callback(
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
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(
            session_factory,
            variant="limited",
            roles=(SystemRoleCode.OWNER, SystemRoleCode.ATHLETE),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        athlete_home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=True,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.telegram_user,
                data=MY_SUBSCRIPTION_ACTION,
                message_id=athlete_home_id,
            ),
        )
        subscription_message = next(
            method
            for method in reversed(methods)
            if isinstance(method, SendPhoto)
        )
        subscription_message_id = sent_message_id(methods, subscription_message)

        stale_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=data.telegram_user,
                data=MY_SUBSCRIPTION_ACTION,
                message_id=athlete_home_id,
            ),
        )
        stale_methods = methods[stale_offset:]
        assert len(stale_methods) == 1
        assert isinstance(stale_methods[0], AnswerCallbackQuery)
        assert stale_methods[0].text == STALE_SCREEN_TEXT

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.telegram_user,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.ROLE_PANEL,
                ).pack(),
                message_id=subscription_message_id,
            ),
        )
        home = last_screen(methods)
        assert home.text == (
            "Показывайте свой QR-код, просматривайте расписание и "
            "информацию об абонементе."
        )
        assert MY_SUBSCRIPTION_ACTION in callback_texts(home)
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()
