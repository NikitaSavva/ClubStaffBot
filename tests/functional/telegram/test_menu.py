from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.identity import GetUserMenuContextInteractor
from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import RoleModel, UserModel, UserRoleModel
from presentation.telegram.handlers.menu import USER_NOT_REGISTERED_TEXT
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    BACK_BUTTON_TEXT,
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import RolePanel, RolePanelCallback
from presentation.telegram.states import CreateAthleteStates
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


def command_update(*, update_id: int, telegram_id: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=NOW,
            chat=Chat(id=telegram_id, type=ChatType.PRIVATE),
            from_user=User(
                id=telegram_id,
                is_bot=False,
                first_name="Menu",
                last_name="User",
                username=f"menu_{telegram_id}",
            ),
            text=text,
        ),
    )


def callback_update(
    *,
    update_id: int,
    telegram_id: int,
    data: str,
    message_id: int = 1,
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=User(
                id=telegram_id,
                is_bot=False,
                first_name="Menu",
                last_name="User",
            ),
            chat_instance=f"chat-{telegram_id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=NOW,
                chat=Chat(id=telegram_id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                caption="UI screen",
            ),
        ),
    )


async def add_user_with_roles(
    container: AsyncContainer,
    *,
    telegram_id: int,
    role_codes: tuple[SystemRoleCode, ...],
) -> None:
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    async with session_factory.begin() as session:
        user = UserModel(
            telegram_id=telegram_id,
            username=f"menu_{telegram_id}",
            first_name="Menu",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(user)
        await session.flush()
        for role_code in role_codes:
            role = await session.scalar(
                select(RoleModel).where(RoleModel.code == role_code.value)
            )
            assert role is not None
            session.add(
                UserRoleModel(
                    user_id=user.id,
                    role_id=role.id,
                    assigned_by_user_id=None,
                    assigned_at=NOW,
                )
            )


@pytest.mark.parametrize(
    ("role_code", "expected_caption", "expected_banner", "expected_rows"),
    [
        (
            SystemRoleCode.OWNER,
            (
                "Меню владельца\n\nУправляйте спортсменами, "
                "Telegram-аккаунтами и ролями пользователей."
            ),
            "owner-banner-file-id",
            [
                [("Сканировать QR", None)],
                [("Отметить вход", "administrator.confirm_attendance")],
                [("Расписание", "administrator.schedule")],
                [
                    (
                        "Выдать абонемент",
                        "administrator.activate_subscription",
                    )
                ],
                [("Добавить спортсмена", "administrator.create_athlete")],
                [("Назначить тренера", "administrator.assign_trainer")],
                [
                    ("Пользователи", "administrator.manage_users"),
                    ("Связать аккаунт", "administrator.link_athlete_account"),
                ],
            ],
        ),
        (
            SystemRoleCode.ADMINISTRATOR,
            (
                "Меню администратора\n\nДобавляйте спортсменов, "
                "связывайте их с Telegram и управляйте ролями "
                "пользователей."
            ),
            "admin-banner-file-id",
            [
                [("Сканировать QR", None)],
                [("Отметить вход", "administrator.confirm_attendance")],
                [("Расписание", "administrator.schedule")],
                [
                    (
                        "Выдать абонемент",
                        "administrator.activate_subscription",
                    )
                ],
                [("Добавить спортсмена", "administrator.create_athlete")],
                [("Назначить тренера", "administrator.assign_trainer")],
                [
                    ("Пользователи", "administrator.manage_users"),
                    ("Связать аккаунт", "administrator.link_athlete_account"),
                ],
            ],
        ),
        (
            SystemRoleCode.TRAINER,
            "Просматривайте свое расписание тренировок.",
            "trainer-banner-file-id",
            [[("Расписание", "trainer.schedule")]],
        ),
        (
            SystemRoleCode.ATHLETE,
            "Показывайте свой QR-код, просматривайте расписание и "
            "информацию об абонементе.",
                "athlete-banner-file-id",
                [
                    [("Мой QR", "athlete.my_qr")],
                    [("Расписание", "athlete.schedule")],
                [("Мой абонемент", "athlete.my_subscription")],
            ],
        ),
    ],
)
async def test_start_opens_single_role_panel_without_back(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    role_code: SystemRoleCode,
    expected_caption: str,
    expected_banner: str,
    expected_rows: list[list[tuple[str, str | None]]],
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
    telegram_id = 6_000_000 + uuid4().int % 1_000_000_000
    try:
        await bootstrap_system_roles(container)
        await add_user_with_roles(
            container,
            telegram_id=telegram_id,
            role_codes=(role_code,),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, telegram_id=telegram_id, text="/start"),
        )
    finally:
        await container.close()

    assert len(methods) == 1
    method = methods[0]
    assert isinstance(method, SendPhoto)
    assert method.photo == expected_banner
    assert method.caption == expected_caption
    assert method.reply_markup is not None
    actual_rows = [
        [(button.text, button.callback_data) for button in row]
        for row in method.reply_markup.inline_keyboard
    ]
    assert actual_rows == expected_rows
    scanner_buttons = [
        button
        for row in method.reply_markup.inline_keyboard
        for button in row
        if button.text == "Сканировать QR"
    ]
    if role_code in (
        SystemRoleCode.OWNER,
        SystemRoleCode.ADMINISTRATOR,
    ):
        assert len(scanner_buttons) == 1
        assert scanner_buttons[0].callback_data is None
        assert scanner_buttons[0].web_app is not None
        assert scanner_buttons[0].web_app.url == (
            "https://scanner.example.test/webapp/scanner"
        )
    else:
        assert scanner_buttons == []
    assert all(
        button.text != BACK_BUTTON_TEXT
        for row in method.reply_markup.inline_keyboard
        for button in row
    )


@pytest.mark.parametrize("command", ["/start", "/menu"])
async def test_single_owner_without_banner_opens_text_only_owner_home(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    settings = integration_settings.model_copy(
        update={"owner_panel_banner_file_id": None}
    )
    container = create_container(settings)
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
    telegram_id = 6_500_000 + uuid4().int % 1_000_000_000
    try:
        await bootstrap_system_roles(container)
        await add_user_with_roles(
            container,
            telegram_id=telegram_id,
            role_codes=(SystemRoleCode.OWNER,),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=1,
                telegram_id=telegram_id,
                text=command,
            ),
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=telegram_id,
            user_id=telegram_id,
        )
        ui_data = await dispatcher.storage.get_data(storage_key)
    finally:
        await container.close()

    assert len(methods) == 1
    assert isinstance(methods[0], SendMessage)
    assert methods[0].text.startswith("Меню владельца")
    assert not any(isinstance(method, SendPhoto) for method in methods)
    assert ui_data["ui_context"]["navigation"]["active_role"] == "owner"


async def test_multi_role_user_returns_from_panel_to_role_selector(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    callback_order: list[str] = []
    record_callback_order = False

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        if record_callback_order and isinstance(method, AnswerCallbackQuery):
            callback_order.append("ack")
        return telegram_method_result(method, message_id=len(methods))

    original_menu_call = GetUserMenuContextInteractor.__call__

    async def tracked_menu_call(
        interactor: GetUserMenuContextInteractor,
        query: Any,
    ) -> Any:
        if record_callback_order:
            callback_order.append("interactor")
        return await original_menu_call(interactor, query)

    monkeypatch.setattr(
        GetUserMenuContextInteractor,
        "__call__",
        tracked_menu_call,
    )
    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 7_000_000 + uuid4().int % 1_000_000_000
    select_admin = RolePanelCallback(role=RolePanel.ADMINISTRATOR).pack()
    back_to_selector = NavigationCallback(
        action=NavigationAction.BACK,
        target=NavigationTarget.ROLE_SELECTOR,
    ).pack()
    try:
        await bootstrap_system_roles(container)
        await add_user_with_roles(
            container,
            telegram_id=telegram_id,
            role_codes=tuple(SystemRoleCode),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)

        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, telegram_id=telegram_id, text="/start"),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                telegram_id=telegram_id,
                data=select_admin,
                message_id=1,
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                telegram_id=telegram_id,
                data=select_admin,
                message_id=1,
            ),
        )
        record_callback_order = True
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                telegram_id=telegram_id,
                data=back_to_selector,
                message_id=3,
            ),
        )

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=telegram_id,
            user_id=telegram_id,
        )
        ui_data = await dispatcher.storage.get_data(storage_key)
    finally:
        await container.close()

    sends = [method for method in methods if isinstance(method, SendPhoto)]
    answers = [
        method for method in methods if isinstance(method, AnswerCallbackQuery)
    ]
    assert len(sends) == 3
    assert sends[0].photo == "role-selector-banner-file-id"
    assert sends[1].photo == "admin-banner-file-id"
    assert sends[1].reply_markup is not None
    assert any(
        button.callback_data == back_to_selector
        for row in sends[1].reply_markup.inline_keyboard
        for button in row
    )
    assert sends[2].photo == "role-selector-banner-file-id"
    assert sends[0].reply_markup is not None
    assert sends[1].reply_markup is not None
    assert len(answers) == 3
    assert answers[1].text == STALE_SCREEN_TEXT
    assert callback_order == ["ack", "interactor"]
    positions = {id(method): index for index, method in enumerate(methods)}
    assert positions[id(answers[0])] < positions[id(sends[1])]
    assert positions[id(answers[2])] < positions[id(sends[2])]
    assert ui_data["ui_context"]["active_message"]["message_id"] == 6


async def test_owner_and_administrator_keep_selected_presentation_role(
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
    telegram_id = 7_500_000 + uuid4().int % 1_000_000_000
    select_owner = RolePanelCallback(role=RolePanel.OWNER).pack()
    select_admin = RolePanelCallback(role=RolePanel.ADMINISTRATOR).pack()
    back_to_selector = NavigationCallback(
        action=NavigationAction.BACK,
        target=NavigationTarget.ROLE_SELECTOR,
    ).pack()
    try:
        await bootstrap_system_roles(container)
        await add_user_with_roles(
            container,
            telegram_id=telegram_id,
            role_codes=(
                SystemRoleCode.OWNER,
                SystemRoleCode.ADMINISTRATOR,
            ),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=telegram_id,
            user_id=telegram_id,
        )

        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, telegram_id=telegram_id, text="/menu"),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                telegram_id=telegram_id,
                data=select_owner,
                message_id=1,
            ),
        )
        owner_data = await dispatcher.storage.get_data(storage_key)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                telegram_id=telegram_id,
                data=back_to_selector,
                message_id=3,
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                telegram_id=telegram_id,
                data=select_admin,
                message_id=5,
            ),
        )
        admin_data = await dispatcher.storage.get_data(storage_key)
    finally:
        await container.close()

    screens = [method for method in methods if isinstance(method, SendPhoto)]
    assert [screen.photo for screen in screens] == [
        "role-selector-banner-file-id",
        "owner-banner-file-id",
        "role-selector-banner-file-id",
        "admin-banner-file-id",
    ]
    assert screens[1].caption is not None
    assert screens[1].caption.startswith("Меню владельца")
    assert screens[3].caption is not None
    assert screens[3].caption.startswith("Меню администратора")
    assert owner_data["ui_context"]["navigation"]["active_role"] == "owner"
    assert (
        admin_data["ui_context"]["navigation"]["active_role"]
        == "administrator"
    )


@pytest.mark.parametrize("command", ["/start", "/menu", "/start stale-token"])
@pytest.mark.parametrize(
    ("role_codes", "expected_caption", "expected_banner"),
    [
        (
            (SystemRoleCode.ADMINISTRATOR,),
            (
                "Меню администратора\n\nДобавляйте спортсменов, "
                "связывайте их с Telegram и управляйте ролями "
                "пользователей."
            ),
            "admin-banner-file-id",
        ),
        (
            (SystemRoleCode.OWNER,),
            (
                "Меню владельца\n\nУправляйте спортсменами, "
                "Telegram-аккаунтами и ролями пользователей."
            ),
            "owner-banner-file-id",
        ),
        (
            (SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER),
            "Выберите роль, в которой хотите продолжить работу.",
            "role-selector-banner-file-id",
        ),
    ],
)
async def test_registered_command_recovers_from_stale_fsm_and_ui_anchor(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    role_codes: tuple[SystemRoleCode, ...],
    expected_caption: str,
    expected_banner: str,
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
    telegram_id = 8_000_000 + uuid4().int % 1_000_000_000
    try:
        await bootstrap_system_roles(container)
        await add_user_with_roles(
            container,
            telegram_id=telegram_id,
            role_codes=role_codes,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, telegram_id=telegram_id, text="/start"),
        )
        assert len([item for item in methods if isinstance(item, SendPhoto)]) == 1

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=telegram_id,
            user_id=telegram_id,
        )
        stale_data = await dispatcher.storage.get_data(storage_key)
        stale_data["flow_context"] = {"first_name": "Не сохранять"}
        await dispatcher.storage.set_data(storage_key, stale_data)
        await dispatcher.storage.set_state(
            storage_key,
            CreateAthleteStates.waiting_for_first_name.state,
        )

        recovery_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=2,
                telegram_id=telegram_id,
                text=command,
            ),
        )
        recovery_methods = methods[recovery_offset:]
        assert len(recovery_methods) == 1
        recovered = recovery_methods[0]
        assert isinstance(recovered, SendPhoto)
        assert recovered.photo == expected_banner
        assert recovered.caption == expected_caption

        assert await dispatcher.storage.get_state(storage_key) is None
        recovered_data = await dispatcher.storage.get_data(storage_key)
        assert "flow_context" not in recovered_data
        assert recovered_data["ui_context"]["active_message"][
            "message_id"
        ] == len(methods)
    finally:
        await container.close()


@pytest.mark.parametrize("command", ["/start", "/menu"])
async def test_unregistered_recovery_command_does_not_create_user(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
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
    telegram_id = 9_000_000 + uuid4().int % 1_000_000_000
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=1,
                telegram_id=telegram_id,
                text=command,
            ),
        )
        assert len(methods) == 1
        method = methods[0]
        assert isinstance(method, SendPhoto)
        assert method.caption == USER_NOT_REGISTERED_TEXT

        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        async with session_factory() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.telegram_id == telegram_id)
            )
        assert user is None
    finally:
        await container.close()
