from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
    EditMessageReplyMarkup,
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.athlete_creation import (
    CONFIRM_CREATE_ATHLETE_ACTION,
    CONFIRM_CREATE_ATHLETE_TEXT,
    CREATE_ATHLETE_ACTION,
    CREATE_ATHLETE_CANCELLED_TEXT,
    CREATE_ATHLETE_PERMISSION_DENIED_TEXT,
    CREATE_ATHLETE_SUCCESS_TEXT,
    ENTER_FIRST_NAME_TEXT,
    INVALID_FIRST_NAME_TEXT,
)
from presentation.telegram.navigation import (
    CANCEL_BUTTON_TEXT,
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.states import CreateAthleteStates
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


def telegram_user(telegram_id: int) -> User:
    return User(
        id=telegram_id,
        is_bot=False,
        first_name="Admin",
        last_name="User",
        username=f"manual_admin_{telegram_id}",
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
    data: str = CREATE_ATHLETE_ACTION,
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


async def add_user_with_role(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_id: int,
    role_code: SystemRoleCode,
) -> int:
    async with session_factory.begin() as session:
        role = await session.scalar(
            select(RoleModel).where(RoleModel.code == role_code.value)
        )
        assert role is not None
        user = UserModel(
            telegram_id=telegram_id,
            username=f"manual_user_{telegram_id}",
            first_name="Admin",
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
    return user.id


def screen_texts(methods: list[TelegramMethod[Any]]) -> list[str]:
    texts: list[str] = []
    for method in methods:
        if isinstance(method, SendPhoto) and method.caption is not None:
            texts.append(method.caption)
        if (
            isinstance(method, EditMessageCaption)
            and method.caption is not None
        ):
            texts.append(method.caption)
    return texts


def sent_message_id(
    methods: list[TelegramMethod[Any]],
    target: TelegramMethod[Any],
) -> int:
    return next(
        index
        for index, method in enumerate(methods, start=1)
        if method is target
    )


def active_message_id(state_data: dict[str, Any]) -> int:
    ui_context = state_data.get("ui_context")
    assert isinstance(ui_context, dict)
    active_message = ui_context.get("active_message")
    assert isinstance(active_message, dict)
    message_id = active_message.get("message_id")
    assert isinstance(message_id, int)
    return message_id


async def test_administrator_creates_athlete_through_menu_flow(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 16_000_000 + uuid4().int % 1_000_000_000
    first_name = f"Ирина-{uuid4().hex[:8]}"
    sender = telegram_user(telegram_id)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        actor_user_id = await add_user_with_role(
            session_factory,
            telegram_id=telegram_id,
            role_code=SystemRoleCode.ADMINISTRATOR,
        )
        async with session_factory() as session:
            user_count_before = await session.scalar(
                select(func.count()).select_from(UserModel)
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        menu_method = next(
            method
            for method in sent_methods
            if isinstance(method, SendPhoto)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
        )
        create_button = next(
            button
            for row in menu_method.reply_markup.inline_keyboard
            for button in row
            if button.callback_data == CREATE_ATHLETE_ACTION
        )
        assert create_button.text == "Добавить спортсмена"

        menu_message_id = sent_message_id(sent_methods, menu_method)
        begin_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(update_id=2, sender=sender),
        )
        begin_methods = sent_methods[begin_offset:]
        begin_answers = [
            method
            for method in begin_methods
            if isinstance(method, AnswerCallbackQuery)
        ]
        assert len(begin_answers) == 1
        old_keyboard_cleanup = next(
            method
            for method in begin_methods
            if isinstance(method, EditMessageReplyMarkup)
        )
        prompt_method = next(
            method
            for method in begin_methods
            if isinstance(method, SendPhoto)
        )
        prompt_message_id = sent_message_id(sent_methods, prompt_method)
        assert begin_methods.index(begin_answers[0]) < begin_methods.index(
            old_keyboard_cleanup
        )
        assert old_keyboard_cleanup.message_id == menu_message_id
        assert old_keyboard_cleanup.reply_markup is None
        assert prompt_message_id != menu_message_id
        assert prompt_method.photo == "admin-banner-file-id"
        assert prompt_method.caption == ENTER_FIRST_NAME_TEXT
        assert ENTER_FIRST_NAME_TEXT in screen_texts(sent_methods)

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        prompt_state_data = await dispatcher.storage.get_data(storage_key)
        assert active_message_id(prompt_state_data) == prompt_message_id
        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_first_name.state
        )

        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=3,
                sender=sender,
                text=f"  {first_name}  ",
            ),
        )
        confirmation_method = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
        )
        confirmation_message_id = sent_message_id(
            sent_methods,
            confirmation_method,
        )
        assert confirmation_message_id != prompt_message_id
        assert confirmation_method.photo == "admin-banner-file-id"
        assert confirmation_method.caption == CONFIRM_CREATE_ATHLETE_TEXT.format(
            first_name=first_name
        )
        confirmation_state_data = await dispatcher.storage.get_data(storage_key)
        assert confirmation_state_data["flow_context"] == {
            "first_name": first_name
        }
        assert active_message_id(
            confirmation_state_data
        ) == confirmation_message_id
        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_confirmation.state
        )

        async with session_factory() as session:
            athlete_before_confirmation = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
            audit_count_before_confirmation = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.actor_user_id == actor_user_id,
                )
            )
        assert athlete_before_confirmation is None
        assert audit_count_before_confirmation == 0

        confirm_offset = len(sent_methods)
        send_count_before_confirmation = len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        )
        confirm_methods = sent_methods[confirm_offset:]
        confirm_answers = [
            method
            for method in confirm_methods
            if isinstance(method, AnswerCallbackQuery)
        ]
        success_edit = next(
            method
            for method in confirm_methods
            if isinstance(method, EditMessageCaption)
        )
        assert len(confirm_answers) == 1
        assert confirm_methods.index(confirm_answers[0]) < confirm_methods.index(
            success_edit
        )
        assert success_edit.message_id == confirmation_message_id
        assert success_edit.caption == CREATE_ATHLETE_SUCCESS_TEXT.format(
            first_name=first_name
        )
        assert len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        ) == send_count_before_confirmation
        final_state_data = await dispatcher.storage.get_data(storage_key)
        assert "flow_context" not in final_state_data
        assert active_message_id(final_state_data) == confirmation_message_id
        assert await dispatcher.storage.get_state(storage_key) is None

        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
            user_count_after = await session.scalar(
                select(func.count()).select_from(UserModel)
            )
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.actor_user_id == actor_user_id,
                )
            )
        assert athlete is not None
        assert athlete.user_id is None
        assert athlete.athlete_public_id.version == 4
        assert user_count_after == user_count_before
        assert audit is not None
        assert audit.entity_id == athlete.id
    finally:
        await container.close()


async def test_cancelled_form_does_not_create_athlete_or_audit(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 17_000_000 + uuid4().int % 1_000_000_000
    first_name = f"Cancelled-{uuid4().hex[:8]}"
    sender = telegram_user(telegram_id)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        actor_user_id = await add_user_with_role(
            session_factory,
            telegram_id=telegram_id,
            role_code=SystemRoleCode.ADMINISTRATOR,
        )
        async with session_factory() as session:
            athlete_count_before = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            callback_update(update_id=1, sender=sender),
        )
        form_message = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
            and isinstance(method.reply_markup, InlineKeyboardMarkup)
        )
        cancel_callback = NavigationCallback(
            action=NavigationAction.CANCEL,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        cancel_button = next(
            button
            for row in form_message.reply_markup.inline_keyboard
            for button in row
            if button.callback_data == cancel_callback
        )
        assert cancel_button.text == CANCEL_BUTTON_TEXT
        prompt_message_id = sent_message_id(sent_methods, form_message)

        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text=first_name),
        )
        confirmation_message = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
        )
        confirmation_message_id = sent_message_id(
            sent_methods,
            confirmation_message,
        )
        assert confirmation_message_id != prompt_message_id
        assert confirmation_message.caption == CONFIRM_CREATE_ATHLETE_TEXT.format(
            first_name=first_name
        )

        send_count_before_cancel = len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        )
        cancel_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=sender,
                data=cancel_callback,
            ),
        )
        cancel_methods = sent_methods[cancel_offset:]
        cancel_answers = [
            method
            for method in cancel_methods
            if isinstance(method, AnswerCallbackQuery)
        ]
        return_edit = next(
            method
            for method in cancel_methods
            if isinstance(method, EditMessageCaption)
        )
        assert len(cancel_answers) == 1
        assert cancel_methods.index(cancel_answers[0]) < cancel_methods.index(
            return_edit
        )
        assert return_edit.message_id == confirmation_message_id
        assert len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        ) == send_count_before_cancel

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        assert await dispatcher.storage.get_state(storage_key) is None
        state_data = await dispatcher.storage.get_data(storage_key)
        assert "flow_context" not in state_data
        assert "ui_context" in state_data
        assert active_message_id(state_data) == confirmation_message_id

        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=4,
                sender=sender,
                text="ShouldNotBecomeAthlete",
            ),
        )

        async with session_factory() as session:
            athlete_count_after = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )
            cancelled_athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.actor_user_id == actor_user_id,
                )
            )
        assert any(
            CREATE_ATHLETE_CANCELLED_TEXT in text
            for text in screen_texts(sent_methods)
        )
        assert any(
            "Панель администратора" in text
            for text in screen_texts(sent_methods)
        )
        assert athlete_count_after == athlete_count_before
        assert cancelled_athlete is None
        assert audit_count == 0
    finally:
        await container.close()


async def test_invalid_first_name_keeps_flow_without_business_write(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 17_500_000 + uuid4().int % 1_000_000_000
    sender = telegram_user(telegram_id)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        actor_user_id = await add_user_with_role(
            session_factory,
            telegram_id=telegram_id,
            role_code=SystemRoleCode.ADMINISTRATOR,
        )
        async with session_factory() as session:
            athlete_count_before = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            callback_update(update_id=1, sender=sender),
        )
        prompt_message = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
        )
        prompt_message_id = sent_message_id(sent_methods, prompt_message)

        invalid_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text="   "),
        )
        invalid_methods = sent_methods[invalid_offset:]
        prompt_cleanup = next(
            method
            for method in invalid_methods
            if isinstance(method, EditMessageReplyMarkup)
        )
        invalid_screen = next(
            method
            for method in invalid_methods
            if isinstance(method, SendPhoto)
        )
        invalid_message_id = sent_message_id(sent_methods, invalid_screen)
        assert prompt_cleanup.message_id == prompt_message_id
        assert prompt_cleanup.reply_markup is None
        assert invalid_message_id != prompt_message_id
        assert invalid_screen.caption == INVALID_FIRST_NAME_TEXT
        assert invalid_screen.photo == "admin-banner-file-id"

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        state_data = await dispatcher.storage.get_data(storage_key)
        assert state_data["flow_context"] == {}
        assert active_message_id(state_data) == invalid_message_id
        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_first_name.state
        )

        async with session_factory() as session:
            athlete_count_after = await session.scalar(
                select(func.count()).select_from(AthleteModel)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.actor_user_id == actor_user_id,
                )
            )
        assert athlete_count_after == athlete_count_before
        assert audit_count == 0
    finally:
        await container.close()


async def test_back_from_confirmation_edits_current_active_screen(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    sender = telegram_user(17_750_000 + uuid4().int % 1_000_000_000)
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            callback_update(update_id=1, sender=sender),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text="Иван"),
        )
        confirmation_screen = next(
            method
            for method in reversed(sent_methods)
            if isinstance(method, SendPhoto)
        )
        confirmation_message_id = sent_message_id(
            sent_methods,
            confirmation_screen,
        )
        send_count_before_back = len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        )

        back_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=sender,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.CREATE_ATHLETE_FIRST_NAME,
                ).pack(),
            ),
        )
        back_methods = sent_methods[back_offset:]
        back_answer = next(
            method
            for method in back_methods
            if isinstance(method, AnswerCallbackQuery)
        )
        back_edit = next(
            method
            for method in back_methods
            if isinstance(method, EditMessageCaption)
        )
        assert back_methods.index(back_answer) < back_methods.index(back_edit)
        assert back_edit.message_id == confirmation_message_id
        assert back_edit.caption == ENTER_FIRST_NAME_TEXT
        assert len(
            [method for method in sent_methods if isinstance(method, SendPhoto)]
        ) == send_count_before_back

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        state_data = await dispatcher.storage.get_data(storage_key)
        assert state_data["flow_context"] == {}
        assert active_message_id(state_data) == confirmation_message_id
        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_first_name.state
        )
    finally:
        await container.close()


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_callback_cannot_create_athlete(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    role_code: SystemRoleCode,
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    telegram_id = 18_000_000 + uuid4().int % 1_000_000_000
    sender = telegram_user(telegram_id)
    first_name = f"Forbidden-{uuid4()}"
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        await add_user_with_role(
            session_factory,
            telegram_id=telegram_id,
            role_code=role_code,
        )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            callback_update(update_id=1, sender=sender),
        )
        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=2,
                sender=sender,
                text=first_name,
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        )

        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
        assert CREATE_ATHLETE_PERMISSION_DENIED_TEXT in screen_texts(
            sent_methods
        )
        assert athlete is None
    finally:
        await container.close()
