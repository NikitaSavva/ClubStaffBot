from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AuditLogModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.role_management import (
    ASSIGN_ROLE_PREFIX,
    BEGIN_ASSIGN_ROLE_ACTION,
    MANAGE_USERS_ACTION,
    ROLE_ASSIGNED_TEXT,
    SELECT_USER_PREFIX,
    USER_ROLE_CONTEXT_TEXT,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


def telegram_user(
    telegram_id: int,
    *,
    first_name: str,
    username: str,
) -> User:
    return User(
        id=telegram_id,
        is_bot=False,
        first_name=first_name,
        last_name="User",
        username=username,
    )


def message_update(
    *,
    update_id: int,
    sender: User,
    text: str,
) -> Update:
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
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=sender,
            chat_instance=f"chat-{sender.id}",
            data=data,
            message=Message(
                message_id=update_id,
                date=NOW,
                chat=Chat(id=sender.id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                text="Role management",
            ),
        ),
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


async def add_user_with_role(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str,
    first_name: str,
    role_code: SystemRoleCode,
) -> UserModel:
    user = UserModel(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    assigned_role = await role(session, role_code)
    session.add(
        UserRoleModel(
            user_id=user.id,
            role_id=assigned_role.id,
            assigned_by_user_id=None,
            assigned_at=NOW,
        )
    )
    return user


def last_message_with_keyboard(
    methods: list[TelegramMethod[Any]],
) -> SendMessage:
    return next(
        method
        for method in reversed(methods)
        if isinstance(method, SendMessage)
        and isinstance(method.reply_markup, InlineKeyboardMarkup)
    )


def keyboard_callbacks(message: SendMessage) -> set[str | None]:
    assert isinstance(message.reply_markup, InlineKeyboardMarkup)
    return {
        button.callback_data
        for row in message.reply_markup.inline_keyboard
        for button in row
    }


async def test_administrator_assigns_role_through_telegram_flow(
    integration_settings: Settings,
    monkeypatch: Any,
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
    admin_telegram_id = 23_000_000 + uuid4().int % 1_000_000_000
    target_telegram_id = 24_000_000 + uuid4().int % 1_000_000_000
    suffix = uuid4().hex[:8]
    admin_sender = telegram_user(
        admin_telegram_id,
        first_name="Admin",
        username=f"admin_{suffix}",
    )
    target_sender = telegram_user(
        target_telegram_id,
        first_name=f"Target{suffix}",
        username=f"target_{suffix}",
    )

    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        async with session_factory.begin() as session:
            administrator = await add_user_with_role(
                session,
                telegram_id=admin_telegram_id,
                username=admin_sender.username or "",
                first_name=admin_sender.first_name,
                role_code=SystemRoleCode.ADMINISTRATOR,
            )
            target = await add_user_with_role(
                session,
                telegram_id=target_telegram_id,
                username=target_sender.username or "",
                first_name=target_sender.first_name,
                role_code=SystemRoleCode.ATHLETE,
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=1,
                sender=admin_sender,
                text="/menu",
            ),
        )
        assert MANAGE_USERS_ACTION in keyboard_callbacks(
            last_message_with_keyboard(sent_methods)
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=admin_sender,
                data=MANAGE_USERS_ACTION,
            ),
        )
        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=3,
                sender=admin_sender,
                text=target_sender.first_name,
            ),
        )
        search_message = last_message_with_keyboard(sent_methods)
        assert f"{SELECT_USER_PREFIX}{target.id}" in keyboard_callbacks(
            search_message
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=admin_sender,
                data=f"{SELECT_USER_PREFIX}{target.id}",
            ),
        )
        context_message = last_message_with_keyboard(sent_methods)
        assert context_message.text.startswith(
            USER_ROLE_CONTEXT_TEXT.split("{")[0]
        )
        assert "ATHLETE" in context_message.text
        assert BEGIN_ASSIGN_ROLE_ACTION in keyboard_callbacks(context_message)

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=admin_sender,
                data=BEGIN_ASSIGN_ROLE_ACTION,
            ),
        )
        role_message = last_message_with_keyboard(sent_methods)
        assert keyboard_callbacks(role_message) == {
            f"{ASSIGN_ROLE_PREFIX}{code.value}" for code in SystemRoleCode
        }

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=admin_sender,
                data=f"{ASSIGN_ROLE_PREFIX}{SystemRoleCode.TRAINER.value}",
            ),
        )
        success_message = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendMessage)
        )
        assert success_message.text.startswith(
            ROLE_ASSIGNED_TEXT.split("{")[0]
        )
        assert "ATHLETE" in success_message.text
        assert "TRAINER" in success_message.text

        async with session_factory() as session:
            target_role_codes = set(
                await session.scalars(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == target.id)
                )
            )
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ROLE_ASSIGNED",
                    AuditLogModel.actor_user_id == administrator.id,
                    AuditLogModel.entity_id == target.id,
                )
            )
        assert target_role_codes == {"ATHLETE", "TRAINER"}
        assert audit is not None
        assert audit.payload == {"role_code": "TRAINER"}

        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=7,
                sender=target_sender,
                text="/menu",
            ),
        )
        target_menu_callbacks = keyboard_callbacks(
            last_message_with_keyboard(sent_methods)
        )
        assert "athlete.home" in target_menu_callbacks
        assert "trainer.home" in target_menu_callbacks
    finally:
        await container.close()
