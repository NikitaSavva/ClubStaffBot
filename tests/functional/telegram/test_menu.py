from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User,
)
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import RoleModel, UserModel, UserRoleModel
from presentation.telegram.keyboards.role import ROLE_SWITCH_LABEL
from presentation.telegram.presenters import RolePanel, RolePanelCallback
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
                message_id=1,
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
    (
        "role_code",
        "expected_caption",
        "expected_banner",
        "expected_reply_rows",
    ),
    [
        (
            SystemRoleCode.ADMINISTRATOR,
            "Панель администратора",
            "admin-banner-file-id",
            [
                ["Добавить спортсмена"],
                ["Пользователи", "Связать аккаунт"],
            ],
        ),
        (
            SystemRoleCode.TRAINER,
            "Панель тренера",
            "trainer-banner-file-id",
            [],
        ),
        (
            SystemRoleCode.ATHLETE,
            "Панель спортсмена",
            "athlete-banner-file-id",
            [],
        ),
    ],
)
async def test_start_opens_single_role_panel_without_back(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    role_code: SystemRoleCode,
    expected_caption: str,
    expected_banner: str,
    expected_reply_rows: list[list[str]],
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
    if expected_reply_rows:
        assert isinstance(method.reply_markup, ReplyKeyboardMarkup)
        assert method.reply_markup.resize_keyboard is True
        assert method.reply_markup.is_persistent is True
        assert [
            [button.text for button in row]
            for row in method.reply_markup.keyboard
        ] == expected_reply_rows
    else:
        assert isinstance(method.reply_markup, ReplyKeyboardRemove)


async def test_multi_role_user_switches_role_without_stale_reply_actions(
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
    telegram_id = 7_000_000 + uuid4().int % 1_000_000_000
    select_admin = RolePanelCallback(role=RolePanel.ADMINISTRATOR).pack()
    select_athlete = RolePanelCallback(role=RolePanel.ATHLETE).pack()
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
            ),
        )
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=3,
                telegram_id=telegram_id,
                text=ROLE_SWITCH_LABEL,
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                telegram_id=telegram_id,
                data=select_athlete,
            ),
        )
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=5,
                telegram_id=telegram_id,
                text="Пользователи",
            ),
        )
    finally:
        await container.close()

    sends = [method for method in methods if isinstance(method, SendPhoto)]
    edits = [
        method
        for method in methods
        if isinstance(method, EditMessageReplyMarkup)
    ]
    answers = [
        method for method in methods if isinstance(method, AnswerCallbackQuery)
    ]
    deletes = [
        method for method in methods if isinstance(method, DeleteMessage)
    ]
    assert len(sends) == 4
    assert sends[0].photo == "role-selector-banner-file-id"
    assert isinstance(sends[0].reply_markup, ReplyKeyboardRemove)
    assert sends[1].photo == "admin-banner-file-id"
    assert isinstance(sends[1].reply_markup, ReplyKeyboardMarkup)
    assert [
        [button.text for button in row]
        for row in sends[1].reply_markup.keyboard
    ] == [
        ["Добавить спортсмена"],
        ["Пользователи", "Связать аккаунт"],
        [ROLE_SWITCH_LABEL],
    ]
    assert sends[2].photo == "role-selector-banner-file-id"
    assert isinstance(sends[2].reply_markup, ReplyKeyboardRemove)
    assert sends[3].photo == "athlete-banner-file-id"
    assert isinstance(sends[3].reply_markup, ReplyKeyboardMarkup)
    assert [
        [button.text for button in row]
        for row in sends[3].reply_markup.keyboard
    ] == [[ROLE_SWITCH_LABEL]]
    assert len(edits) == 4
    assert len(answers) == 2
    assert len(deletes) == 1
    assert deletes[0].message_id == 3
