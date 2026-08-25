from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
    EditMessageMedia,
    EditMessageReplyMarkup,
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
from presentation.telegram.navigation import (
    BACK_BUTTON_TEXT,
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from tests.functional.telegram.fakes import telegram_method_result

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
) -> tuple[int, int]:
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
            birth_date=date(1993, 8, 25),
            phone=None,
            is_active=True,
        )
        session.add(athlete)
        await session.flush()
        legacy_athlete = AthleteModel(
            user_id=None,
            first_name="Пётр",
            last_name="Петров",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        session.add(legacy_athlete)
        await session.flush()
        return athlete.id, legacy_athlete.id


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
        sent_methods.append(method)
        return telegram_method_result(
            method,
            message_id=len(sent_methods),
            bot_user=BOT_USER,
        )

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
        athlete_id, legacy_athlete_id = (
            await add_administrator_and_unlinked_athlete(
            container,
            telegram_id=admin_telegram_id,
        )
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
            if isinstance(method, SendPhoto)
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
            if isinstance(method, EditMessageCaption)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
        )
        athlete_button = next(
            button
            for row in athlete_list_method.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
            == f"{SELECT_ATHLETE_PREFIX}{athlete_id}"
        )
        assert athlete_button.text == "Иван Иванов (25.08.1993)"
        assert athlete_button.callback_data == (
            f"{SELECT_ATHLETE_PREFIX}{athlete_id}"
        )
        legacy_button = next(
            button
            for row in athlete_list_method.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
            == f"{SELECT_ATHLETE_PREFIX}{legacy_athlete_id}"
        )
        assert legacy_button.text == "Пётр Петров"

        back_to_menu = NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        back_button = next(
            button
            for row in athlete_list_method.reply_markup.inline_keyboard
            for button in row
            if button.callback_data == back_to_menu
        )
        assert back_button.text == BACK_BUTTON_TEXT

        return_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=admin,
                data=back_to_menu,
            ),
        )
        return_methods = sent_methods[return_offset:]
        list_cleanup = next(
            method
            for method in return_methods
            if isinstance(method, EditMessageReplyMarkup)
        )
        returned_menu = next(
            method
            for method in return_methods
            if isinstance(method, SendPhoto)
        )
        assert list_cleanup.message_id == athlete_list_method.message_id
        assert list_cleanup.reply_markup is None
        assert returned_menu.caption == (
            "Добавляйте спортсменов, связывайте их с Telegram и управляйте "
            "ролями пользователей."
        )
        original_menu_message_id = next(
            index
            for index, method in enumerate(sent_methods, start=1)
            if method is menu_method
        )
        returned_menu_message_id = next(
            index
            for index, method in enumerate(sent_methods, start=1)
            if method is returned_menu
        )
        assert returned_menu_message_id != original_menu_message_id
        async with session_factory() as session:
            invite_count_before_selection = await session.scalar(
                select(func.count()).select_from(BotInviteModel)
            )
        assert invite_count_before_selection == 0

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=admin,
                data=LINK_ACCOUNT_ACTION,
            ),
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=admin,
                data=f"{SELECT_ATHLETE_PREFIX}{athlete_id}",
            ),
        )
        photo_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, EditMessageMedia)
        )
        assert isinstance(photo_method.media.media, BufferedInputFile)
        assert photo_method.media.media.data.startswith(b"\x89PNG")
        assert photo_method.media.caption is not None
        assert photo_method.message_id == returned_menu_message_id
        deep_link = photo_method.media.caption.splitlines()[-1]
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
                update_id=6,
                sender=new_athlete_user,
                text=f"/start {raw_token}",
            ),
        )
        success_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
            if method.chat_id == athlete_telegram_id
        )
        assert success_method.photo == "athlete-banner-file-id"
        assert success_method.caption is not None
        assert success_method.caption.startswith(ACCOUNT_LINK_SUCCESS_TEXT)

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
                update_id=7,
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
            if isinstance(method, SendPhoto)
            if method.chat_id == second_telegram_id
        )
        assert repeat_method.photo == "role-selector-banner-file-id"
        assert repeat_method.caption == INVALID_INVITE_TEXT
        admin_sends = [
            method
            for method in sent_methods
            if isinstance(method, SendPhoto)
            and method.chat_id == admin_telegram_id
        ]
        assert len(admin_sends) == 2
        assert any(
            isinstance(method, AnswerCallbackQuery) for method in sent_methods
        )
    finally:
        await container.close()
