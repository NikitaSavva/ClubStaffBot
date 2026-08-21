from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Message, Update, User
from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import RoleModel, UserModel, UserRoleModel
from presentation.telegram.handlers.menu import MENU_TEXT
from presentation.telegram.navigation import BACK_BUTTON_TEXT

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def synthetic_menu_update(
    *,
    update_id: int,
    telegram_id: int,
) -> Update:
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
            text="/menu",
        ),
    )


async def add_user_with_role(
    container: AsyncContainer,
    *,
    telegram_id: int,
    role_code: SystemRoleCode,
) -> None:
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    async with session_factory.begin() as session:
        role = await session.scalar(
            select(RoleModel).where(RoleModel.code == role_code.value)
        )
        assert role is not None
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
        session.add(
            UserRoleModel(
                user_id=user.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )


@pytest.mark.parametrize(
    ("role_code", "expected_buttons"),
    [
        (
            SystemRoleCode.ADMINISTRATOR,
            (
                ("Меню администратора", "administrator.home"),
                (
                    "Добавить спортсмена",
                    "administrator.create_athlete",
                ),
                (
                    "Связать аккаунт",
                    "administrator.link_athlete_account",
                ),
                (
                    "Пользователи",
                    "administrator.manage_users",
                ),
            ),
        ),
        (
            SystemRoleCode.ATHLETE,
            (("Меню спортсмена", "athlete.home"),),
        ),
        (
            SystemRoleCode.TRAINER,
            (("Меню тренера", "trainer.home"),),
        ),
    ],
)
async def test_synthetic_user_receives_role_keyboard(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    role_code: SystemRoleCode,
    expected_buttons: tuple[tuple[str, str], ...],
) -> None:
    container = create_container(integration_settings)
    sent_methods: list[TelegramMethod[Any]] = []

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        sent_methods.append(method)
        return True

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 6_000_000 + uuid4().int % 1_000_000_000

    try:
        await bootstrap_system_roles(container)
        await add_user_with_role(
            container,
            telegram_id=telegram_id,
            role_code=role_code,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)

        await dispatcher.feed_update(
            bot,
            synthetic_menu_update(
                update_id=1,
                telegram_id=telegram_id,
            ),
        )
    finally:
        await container.close()

    assert len(sent_methods) == 1
    method = sent_methods[0]
    assert isinstance(method, SendMessage)
    assert method.text == MENU_TEXT
    assert isinstance(method.reply_markup, InlineKeyboardMarkup)
    buttons = [row[0] for row in method.reply_markup.inline_keyboard]
    assert [(button.text, button.callback_data) for button in buttons] == list(
        expected_buttons
    )
    assert all(button.text != BACK_BUTTON_TEXT for button in buttons)
