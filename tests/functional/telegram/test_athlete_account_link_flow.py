from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    AnswerCallbackQuery,
    GetMe,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import BotInvitePurpose, SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AthleteModel,
    BotInviteModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.account_link import (
    LINK_ACCOUNT_ACTION,
    SELECT_ATHLETE_PREFIX,
)
from presentation.telegram.handlers.start import (
    ACCOUNT_LINK_SUCCESS_TEXT,
    INVALID_INVITE_TEXT,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


def telegram_user(telegram_id: int, *, first_name: str) -> User:
    return User(
        id=telegram_id,
        is_bot=False,
        first_name=first_name,
        last_name="User",
        username=f"user_{telegram_id}",
    )


def command_update(
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
                text="Menu",
            ),
        ),
    )


async def add_administrator_and_unlinked_athlete(
    container: Any,
    *,
    telegram_id: int,
) -> int:
    session_factory = await container.get(async_sessionmaker[AsyncSession])
    async with session_factory.begin() as session:
        role = await session.scalar(
            select(RoleModel).where(
                RoleModel.code == SystemRoleCode.ADMINISTRATOR.value
            )
        )
        assert role is not None
        administrator = UserModel(
            telegram_id=telegram_id,
            username=f"admin_{telegram_id}",
            first_name="Admin",
            last_name="User",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(administrator)
        await session.flush()
        session.add(
            UserRoleModel(
                user_id=administrator.id,
                role_id=role.id,
                assigned_by_user_id=None,
                assigned_at=NOW,
            )
        )
        athlete = AthleteModel(
            user_id=None,
            first_name="Иван",
            last_name="Иванов",
            phone=None,
            is_active=True,
        )
        session.add(athlete)
        await session.flush()
        return athlete.id


async def test_administrator_qr_links_existing_athlete_without_creating_new_one(
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
        if isinstance(method, GetMe):
            return BOT_USER
        sent_methods.append(method)
        return True

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    admin_telegram_id = 12_000_000 + uuid4().int % 1_000_000_000
    athlete_telegram_id = 13_000_000 + uuid4().int % 1_000_000_000
    second_telegram_id = 14_000_000 + uuid4().int % 1_000_000_000
    admin = telegram_user(admin_telegram_id, first_name="Admin")
    new_athlete_user = telegram_user(
        athlete_telegram_id,
        first_name="Athlete",
    )
    try:
        await bootstrap_system_roles(container)
        athlete_id = await add_administrator_and_unlinked_athlete(
            container,
            telegram_id=admin_telegram_id,
        )
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        async with session_factory() as session:
            athlete_count_before = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, sender=admin, text="/menu"),
        )
        menu_method = next(
            method
            for method in sent_methods
            if isinstance(method, SendMessage)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
            and any(
                button.callback_data == LINK_ACCOUNT_ACTION
                for row in method.reply_markup.inline_keyboard
                for button in row
            )
        )
        assert menu_method is not None

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=admin,
                data=LINK_ACCOUNT_ACTION,
            ),
        )
        athlete_list_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendMessage)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
        )
        athlete_button = next(
            button
            for row in athlete_list_method.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
            == f"{SELECT_ATHLETE_PREFIX}{athlete_id}"
        )
        assert athlete_button.text == "Иванов Иван"
        assert athlete_button.callback_data == (
            f"{SELECT_ATHLETE_PREFIX}{athlete_id}"
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=admin,
                data=f"{SELECT_ATHLETE_PREFIX}{athlete_id}",
            ),
        )
        photo_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
        )
        assert isinstance(photo_method.photo, BufferedInputFile)
        assert photo_method.photo.data.startswith(b"\x89PNG")
        assert photo_method.caption is not None
        deep_link = photo_method.caption.splitlines()[-1]
        parsed_link = urlparse(deep_link)
        raw_token = parse_qs(parsed_link.query)["start"][0]
        assert parsed_link.scheme == "https"
        assert parsed_link.netloc == "t.me"
        assert parsed_link.path == "/staff_test_bot"
        assert raw_token != str(athlete_id)
        assert len(raw_token) >= 32

        async with session_factory() as session:
            invite = await session.scalar(
                select(BotInviteModel).where(
                    BotInviteModel.athlete_id == athlete_id
                )
            )
        assert invite is not None
        assert invite.purpose is BotInvitePurpose.ATHLETE_LINK
        assert invite.token_hash != raw_token
        assert invite.consumed_at is None

        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=4,
                sender=new_athlete_user,
                text=f"/start {raw_token}",
            ),
        )
        success_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendMessage)
        )
        assert success_method.text == ACCOUNT_LINK_SUCCESS_TEXT

        async with session_factory() as session:
            athlete = await session.get(AthleteModel, athlete_id)
            invite = await session.get(BotInviteModel, invite.id)
            athlete_count_after = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )
            linked_user = await session.scalar(
                select(UserModel).where(
                    UserModel.telegram_id == athlete_telegram_id
                )
            )
        assert athlete is not None
        assert invite is not None
        assert linked_user is not None
        assert athlete.user_id == linked_user.id
        assert athlete_count_after == athlete_count_before
        assert invite.consumed_at is not None

        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=5,
                sender=telegram_user(
                    second_telegram_id,
                    first_name="Second",
                ),
                text=f"/start {raw_token}",
            ),
        )
        repeat_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendMessage)
        )
        assert repeat_method.text == INVALID_INVITE_TEXT
        assert any(
            isinstance(method, AnswerCallbackQuery) for method in sent_methods
        )
    finally:
        await container.close()
