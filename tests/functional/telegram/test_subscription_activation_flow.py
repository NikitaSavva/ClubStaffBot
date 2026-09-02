from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.subscriptions import ActivateSubscriptionInteractor
from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionStatus
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    RoleModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
)
from presentation.telegram.handlers.subscription_activation import (
    ACTIVATE_SUBSCRIPTION_ACTION,
    CONFIRM_ACTIVATION_ACTION,
    SELECT_GROUP_PREFIX,
    SELECT_PLAN_PREFIX,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)
EXPIRED_CALLBACK_QUERY_ERROR = (
    "Bad Request: query is too old and response timeout expired or query ID "
    "is invalid"
)
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
    linked_athlete_id: int
    linked_user_id: int
    linked_username: str
    group_id: int
    specific_plan_id: int
    unlimited_plan_id: int


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
            id=f"callback-{update_id}",
            from_user=sender,
            chat_instance=f"chat-{sender.id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=NOW,
                chat=Chat(id=sender.id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                text="Subscription activation",
            ),
        ),
    )


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


async def role(
    session: AsyncSession,
    role_code: SystemRoleCode,
) -> RoleModel:
    result = await session.scalar(
        select(RoleModel).where(RoleModel.code == role_code.value)
    )
    assert result is not None
    return result


async def arrange_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    administrative_role: SystemRoleCode,
) -> FlowData:
    actor_telegram_id = 81_000_000 + uuid4().int % 1_000_000_000
    actor = User(
        id=actor_telegram_id,
        is_bot=False,
        first_name="Admin",
        last_name="User",
        username=f"admin_{uuid4().hex[:8]}",
    )
    async with session_factory.begin() as session:
        linked_username = f"selector_{uuid4().hex[:8]}"
        actor_model = UserModel(
            telegram_id=actor_telegram_id,
            username=actor.username,
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        athlete = AthleteModel(
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            birth_date=date(1991, 12, 27),
            phone=None,
            is_active=True,
        )
        linked_user = UserModel(
            telegram_id=81_000_000 + uuid4().int % 1_000_000_000,
            username=linked_username,
            first_name="Linked",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add_all([actor_model, athlete, linked_user])
        await session.flush()
        linked_athlete = AthleteModel(
            user_id=linked_user.id,
            first_name="Пётр",
            last_name="Поисков",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        session.add(linked_athlete)
        await session.flush()
        assigned_role = await role(session, administrative_role)
        session.add(
            UserRoleModel(
                user_id=actor_model.id,
                role_id=assigned_role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )
        group = await session.scalar(
            select(TrainingGroupModel)
            .where(TrainingGroupModel.group_type == TrainingGroupType.REGULAR)
            .order_by(TrainingGroupModel.id)
        )
        specific_plan = await session.scalar(
            select(SubscriptionPlanModel).where(
                SubscriptionPlanModel.code == "12_VISITS"
            )
        )
        unlimited_plan = await session.scalar(
            select(SubscriptionPlanModel).where(
                SubscriptionPlanModel.code == "UNLIMITED"
            )
        )
        assert group is not None
        assert specific_plan is not None
        assert unlimited_plan is not None
    return FlowData(
        actor=actor,
        actor_user_id=actor_model.id,
        athlete_id=athlete.id,
        linked_athlete_id=linked_athlete.id,
        linked_user_id=linked_user.id,
        linked_username=linked_username,
        group_id=group.id,
        specific_plan_id=specific_plan.id,
        unlimited_plan_id=unlimited_plan.id,
    )


async def cleanup_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    async with session_factory.begin() as session:
        subscription_ids = tuple(
            await session.scalars(
                select(SubscriptionModel.id).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
        )
        if subscription_ids:
            await session.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.entity_type == "SUBSCRIPTION",
                    AuditLogModel.entity_id.in_(subscription_ids),
                )
            )
        await session.execute(
            delete(AuditLogModel).where(
                AuditLogModel.actor_user_id == data.actor_user_id
            )
        )
        await session.execute(
            delete(SubscriptionModel).where(
                SubscriptionModel.athlete_id == data.athlete_id
            )
        )
        await session.execute(
            delete(UserRoleModel).where(
                UserRoleModel.user_id == data.actor_user_id
            )
        )
        await session.execute(
            delete(AthleteModel).where(
                AthleteModel.id.in_(
                    (data.athlete_id, data.linked_athlete_id)
                )
            )
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == data.linked_user_id)
        )
        await session.execute(
            delete(UserModel).where(UserModel.id == data.actor_user_id)
        )


async def open_confirmation(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
    plan_id: int,
    choose_group: bool,
) -> int:
    await dispatcher.feed_update(
        bot,
        command_update(update_id=1, sender=data.actor, text="/menu"),
    )
    menu = next(method for method in methods if isinstance(method, SendPhoto))
    menu_id = sent_message_id(methods, menu)
    assert ACTIVATE_SUBSCRIPTION_ACTION in callback_texts(last_screen(methods))

    entry_offset = len(methods)
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=2,
            sender=data.actor,
            data=ACTIVATE_SUBSCRIPTION_ACTION,
            message_id=menu_id,
        ),
    )
    entry_methods = methods[entry_offset:]
    athlete_method = next(
        method for method in entry_methods if isinstance(method, SendMessage)
    )
    athlete_screen_id = sent_message_id(methods, athlete_method)
    athlete_screen = last_screen(methods)
    assert athlete_screen.text.startswith("Выдача абонемента")
    assert callback_texts(athlete_screen)[
        AthleteSelectorCallback(
            purpose=AthleteSelectionPurpose.SUBSCRIPTION,
            action=AthleteSelectorAction.SELECT,
            value=str(data.athlete_id),
        ).pack()
    ] == "Иван Иванов (27.12.1991)"

    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=3,
            sender=data.actor,
            data=AthleteSelectorCallback(
                purpose=AthleteSelectionPurpose.SUBSCRIPTION,
                action=AthleteSelectorAction.SELECT,
                value=str(data.athlete_id),
            ).pack(),
            message_id=athlete_screen_id,
        ),
    )
    plan_screen = last_screen(methods)
    assert "Выберите тариф" in plan_screen.text
    assert f"{SELECT_PLAN_PREFIX}{plan_id}" in callback_texts(plan_screen)

    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=4,
            sender=data.actor,
            data=f"{SELECT_PLAN_PREFIX}{plan_id}",
            message_id=athlete_screen_id,
        ),
    )
    if choose_group:
        group_screen = last_screen(methods)
        assert group_screen.text == (
            "Выдача абонемента\n\n"
            "Спортсмен:\nИван Иванов\n\n"
            "Тариф:\n12 посещений — 6 000 ₽\n\n"
            "Выберите группу:"
        )
        assert all(
            detail not in group_screen.text
            for detail in (
                "Кикбоксинг",
                "Сборная",
                "ПН–СБ",
                "16:00",
                "17:30",
                "1. ",
            )
        )
        group_buttons = callback_texts(group_screen)
        assert group_buttons[f"{SELECT_GROUP_PREFIX}{data.group_id}"] == (
            "K1 · Сборная · 16:00"
        )
        assert "ПН–СБ" not in group_buttons[
            f"{SELECT_GROUP_PREFIX}{data.group_id}"
        ]
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.actor,
                data=f"{SELECT_GROUP_PREFIX}{data.group_id}",
                message_id=athlete_screen_id,
            ),
        )
    confirmation = last_screen(methods)
    assert confirmation.text.startswith("Выдать абонемент?")
    assert CONFIRM_ACTIVATION_ACTION in callback_texts(confirmation)
    return athlete_screen_id


async def test_common_selector_searches_surname_and_snapshot_username(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, sender=data.actor, text="/menu"),
        )
        menu = next(
            method for method in methods if isinstance(method, SendPhoto)
        )
        menu_id = sent_message_id(methods, menu)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.actor,
                data=ACTIVATE_SUBSCRIPTION_ACTION,
                message_id=menu_id,
            ),
        )
        selector = next(
            method for method in methods if isinstance(method, SendMessage)
        )
        selector_id = sent_message_id(methods, selector)
        search_callback = AthleteSelectorCallback(
            purpose=AthleteSelectionPurpose.SUBSCRIPTION,
            action=AthleteSelectorAction.SEARCH,
            value="0",
        ).pack()

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.actor,
                data=search_callback,
                message_id=selector_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            command_update(update_id=4, sender=data.actor, text="иванов"),
        )
        surname_result = last_screen(methods)
        assert surname_result.text.startswith("Результаты поиска")
        assert "Иван Иванов (27.12.1991)" in callback_texts(
            surname_result
        ).values()

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.actor,
                data=search_callback,
                message_id=selector_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=6,
                sender=data.actor,
                text=f"missing-{uuid4().hex}",
            ),
        )
        no_result = last_screen(methods)
        assert "Спортсмен не найден" in no_result.text
        assert "«Добавить спортсмена»" in no_result.text

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=data.actor,
                data=search_callback,
                message_id=selector_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=8,
                sender=data.actor,
                text=f"@{data.linked_username.swapcase()}",
            ),
        )
        username_result = last_screen(methods)
        username_callbacks = callback_texts(username_result)
        select_linked = AthleteSelectorCallback(
            purpose=AthleteSelectionPurpose.SUBSCRIPTION,
            action=AthleteSelectorAction.SELECT,
            value=str(data.linked_athlete_id),
        ).pack()
        assert username_callbacks[select_linked] == "Пётр Поисков"
        assert all(
            data.linked_username not in callback
            for callback in username_callbacks
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=9,
                sender=data.actor,
                data=select_linked,
                message_id=selector_id,
            ),
        )
        assert "Выберите тариф" in last_screen(methods).text
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_specific_group_activation_flow_for_administrator_and_owner(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    administrative_role: SystemRoleCode,
) -> None:
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
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=administrative_role,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            plan_id=data.specific_plan_id,
            choose_group=True,
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=data.actor,
                data=CONFIRM_ACTIVATION_ACTION,
                message_id=confirmation_id,
            ),
        )

        success = last_screen(methods)
        assert success.text.startswith("Абонемент активирован")
        assert "Осталось посещений:\n12" in success.text
        async with session_factory() as session:
            subscription = await session.scalar(
                select(SubscriptionModel).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
            audits = (
                await session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                        AuditLogModel.actor_user_id == data.actor_user_id,
                    )
                )
            ).all()
        assert subscription is not None
        assert subscription.group_id == data.group_id
        assert subscription.remaining_visits == 12
        assert len(audits) == 1
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_expired_confirmation_does_not_call_activation_interactor(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    expired_callback_id = "callback-6"

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        if (
            isinstance(method, AnswerCallbackQuery)
            and method.callback_query_id == expired_callback_id
        ):
            raise TelegramBadRequest(
                method=method,
                message=EXPIRED_CALLBACK_QUERY_ERROR,
            )
        return telegram_method_result(method, message_id=len(methods))

    activation_call = AsyncMock()
    monkeypatch.setattr(
        ActivateSubscriptionInteractor,
        "__call__",
        activation_call,
    )
    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    session_factory: async_sessionmaker[AsyncSession] | None = None
    data: FlowData | None = None
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            plan_id=data.specific_plan_id,
            choose_group=True,
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=data.actor.id,
            user_id=data.actor.id,
        )
        state_before = await dispatcher.storage.get_state(storage_key)
        state_data_before = await dispatcher.storage.get_data(storage_key)
        confirmation_offset = len(methods)

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=data.actor,
                data=CONFIRM_ACTIVATION_ACTION,
                message_id=confirmation_id,
            ),
        )

        activation_call.assert_not_awaited()
        confirmation_methods = methods[confirmation_offset:]
        assert len(confirmation_methods) == 1
        assert isinstance(confirmation_methods[0], AnswerCallbackQuery)
        assert await dispatcher.storage.get_state(storage_key) == state_before
        assert (
            await dispatcher.storage.get_data(storage_key)
            == state_data_before
        )
        async with session_factory() as session:
            subscription_count = await session.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
            audit_count = await session.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                    AuditLogModel.actor_user_id == data.actor_user_id,
                )
            )
        assert subscription_count == 0
        assert audit_count == 0
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_unlimited_skips_group_selection(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            plan_id=data.unlimited_plan_id,
            choose_group=False,
        )
        confirmation = last_screen(methods)
        assert "Все обычные группы клуба" in confirmation.text
        assert "Выберите группу" not in confirmation.text

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.actor,
                data=CONFIRM_ACTIVATION_ACTION,
                message_id=confirmation_id,
            ),
        )

        success = last_screen(methods)
        assert "Без ограничений" in success.text
        async with session_factory() as session:
            subscription = await session.scalar(
                select(SubscriptionModel).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
        assert subscription is not None
        assert subscription.group_id is None
        assert subscription.remaining_visits is None
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_cancel_freezes_confirmation_and_stale_callback_cannot_activate(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            plan_id=data.specific_plan_id,
            choose_group=True,
        )
        cancel = NavigationCallback(
            action=NavigationAction.CANCEL,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        cancel_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=data.actor,
                data=cancel,
                message_id=confirmation_id,
            ),
        )
        cancel_methods = methods[cancel_offset:]
        new_home = next(
            method for method in cancel_methods if isinstance(method, SendPhoto)
        )
        assert "Выдача абонемента отменена" in (new_home.caption or "")

        stale_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=data.actor,
                data=CONFIRM_ACTIVATION_ACTION,
                message_id=confirmation_id,
            ),
        )
        stale_methods = methods[stale_offset:]
        assert len(stale_methods) == 1
        assert isinstance(stale_methods[0], AnswerCallbackQuery)
        assert stale_methods[0].text == STALE_SCREEN_TEXT
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
        assert count == 0
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_existing_active_subscription_is_a_controlled_ui_error(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        async with session_factory.begin() as session:
            session.add(
                SubscriptionModel(
                    athlete_id=data.athlete_id,
                    group_id=data.group_id,
                    plan_id=data.specific_plan_id,
                    activated_by_user_id=data.actor_user_id,
                    activated_at=NOW,
                    starts_at=NOW,
                    expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                    activation_price=Decimal("6000"),
                    remaining_visits=12,
                    status=SubscriptionStatus.ACTIVE,
                )
            )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            plan_id=data.specific_plan_id,
            choose_group=True,
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=data.actor,
                data=CONFIRM_ACTIVATION_ACTION,
                message_id=confirmation_id,
            ),
        )

        error_screen = last_screen(methods)
        assert "уже есть действующий абонемент" in error_screen.text
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
            audit_count = await session.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.action == "SUBSCRIPTION_ACTIVATED",
                    AuditLogModel.actor_user_id == data.actor_user_id,
                )
            )
        assert count == 1
        assert audit_count == 0
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()
