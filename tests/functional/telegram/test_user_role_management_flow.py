from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageCaption,
    EditMessageMedia,
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
    BEGIN_ASSIGN_ROLE_PREFIX,
    BEGIN_REMOVE_ROLE_PREFIX,
    ENTER_USER_QUERY_TEXT,
    INVALID_USER_QUERY_TEXT,
    MANAGE_USERS_ACTION,
    REMOVE_ROLE_PREFIX,
    ROLE_ASSIGNED_TEXT,
    ROLE_REMOVED_TEXT,
    SELECT_USER_PREFIX,
    SELECT_USER_TEXT,
    USER_ROLE_CONTEXT_TEXT,
    USER_SELECTION_UNAVAILABLE_TEXT,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    BACK_BUTTON_TEXT,
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import RolePanel, RolePanelCallback
from presentation.telegram.states import RoleManagementStates
from tests.functional.telegram.fakes import telegram_method_result

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
    message_id: int | None = None,
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=sender,
            chat_instance=f"chat-{sender.id}",
            data=data,
            message=Message(
                message_id=(update_id if message_id is None else message_id),
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


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup


def last_message_with_keyboard(
    methods: list[TelegramMethod[Any]],
) -> ScreenSnapshot:
    for method in reversed(methods):
        if isinstance(method, SendPhoto):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, EditMessageCaption):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, EditMessageMedia):
            text = method.media.caption
            reply_markup = method.reply_markup
        else:
            continue
        if text is not None and isinstance(reply_markup, InlineKeyboardMarkup):
            return ScreenSnapshot(text=text, reply_markup=reply_markup)
    raise AssertionError("No rendered screen with inline keyboard")


def keyboard_callbacks(message: ScreenSnapshot) -> set[str | None]:
    return {
        button.callback_data
        for row in message.reply_markup.inline_keyboard
        for button in row
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


async def test_invalid_user_query_stays_visible_and_renders_compact_error(
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
    sender = telegram_user(
        22_500_000 + uuid4().int % 1_000_000_000,
        first_name="Admin",
        username=f"admin_{uuid4().hex[:8]}",
    )
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        menu_screen = next(
            method for method in methods if isinstance(method, SendPhoto)
        )
        menu_message_id = sent_message_id(methods, menu_screen)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                data=MANAGE_USERS_ACTION,
                message_id=menu_message_id,
            ),
        )

        invalid_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text="   "),
        )
        invalid_methods = methods[invalid_offset:]
        assert not any(
            isinstance(method, DeleteMessage) for method in invalid_methods
        )
        error_screen = next(
            method
            for method in invalid_methods
            if isinstance(method, SendMessage)
        )
        assert error_screen.text == INVALID_USER_QUERY_TEXT
        assert error_screen.reply_markup is not None
        assert not any(
            isinstance(method, SendPhoto) for method in invalid_methods
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        assert await dispatcher.storage.get_state(storage_key) == (
            RoleManagementStates.waiting_for_query.state
        )
    finally:
        await container.close()


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrative_actor_assigns_role_through_telegram_flow(
    integration_settings: Settings,
    monkeypatch: Any,
    administrative_role: SystemRoleCode,
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
        first_name=f"TargetA{suffix}",
        username=f"target_{suffix}",
    )
    second_target_sender = telegram_user(
        target_telegram_id + 1,
        first_name=f"TargetB{suffix}",
        username=f"target_second_{suffix}",
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
                role_code=administrative_role,
            )
            target = await add_user_with_role(
                session,
                telegram_id=target_telegram_id,
                username=target_sender.username or "",
                first_name=target_sender.first_name,
                role_code=SystemRoleCode.ATHLETE,
            )
            second_target = await add_user_with_role(
                session,
                telegram_id=second_target_sender.id,
                username=second_target_sender.username or "",
                first_name=second_target_sender.first_name,
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
        menu_screen = next(
            method
            for method in sent_methods
            if isinstance(method, SendPhoto)
            and method.chat_id == admin_telegram_id
        )
        menu_message_id = sent_message_id(sent_methods, menu_screen)

        begin_search_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=admin_sender,
                data=MANAGE_USERS_ACTION,
                message_id=menu_message_id,
            ),
        )
        begin_search_methods = sent_methods[begin_search_offset:]
        begin_search_answer = next(
            method
            for method in begin_search_methods
            if isinstance(method, AnswerCallbackQuery)
        )
        prompt_screen = next(
            method
            for method in begin_search_methods
            if isinstance(method, SendMessage)
        )
        prompt_message_id = sent_message_id(sent_methods, prompt_screen)
        assert begin_search_methods.index(
            begin_search_answer
        ) < begin_search_methods.index(prompt_screen)
        assert menu_screen.reply_markup is not None
        assert prompt_message_id != menu_message_id
        assert prompt_screen.text == ENTER_USER_QUERY_TEXT
        assert prompt_screen.reply_markup is not None
        assert not any(
            isinstance(method, SendPhoto) for method in begin_search_methods
        )

        search_result_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=3,
                sender=admin_sender,
                text=suffix,
            ),
        )
        search_result_methods = sent_methods[search_result_offset:]
        query_cleanup = next(
            method
            for method in search_result_methods
            if isinstance(method, DeleteMessage)
        )
        result_screen = next(
            method
            for method in search_result_methods
            if isinstance(method, SendPhoto)
        )
        result_message_id = sent_message_id(sent_methods, result_screen)
        assert query_cleanup.message_id == 3
        assert search_result_methods.index(query_cleanup) < (
            search_result_methods.index(result_screen)
        )
        assert prompt_screen.reply_markup is not None
        assert result_message_id != prompt_message_id
        assert result_screen.caption == SELECT_USER_TEXT
        assert result_screen.photo == "admin-banner-file-id"
        search_message = last_message_with_keyboard(sent_methods)
        assert f"{SELECT_USER_PREFIX}{target.id}" in keyboard_callbacks(
            search_message
        )

        stale_offset = len(sent_methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=40,
                sender=admin_sender,
                data=MANAGE_USERS_ACTION,
                message_id=menu_message_id,
            ),
        )
        stale_methods = sent_methods[stale_offset:]
        assert len(stale_methods) == 1
        stale_answer = stale_methods[0]
        assert isinstance(stale_answer, AnswerCallbackQuery)
        assert stale_answer.text == STALE_SCREEN_TEXT

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=admin_sender,
                data=f"{SELECT_USER_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )
        context_message = last_message_with_keyboard(sent_methods)
        assert context_message.text.startswith(
            USER_ROLE_CONTEXT_TEXT.split("{")[0]
        )
        assert "ATHLETE" in context_message.text
        assert (
            f"{BEGIN_ASSIGN_ROLE_PREFIX}{target.id}"
            in keyboard_callbacks(context_message)
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=admin_sender,
                data=f"{BEGIN_ASSIGN_ROLE_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )
        role_message = last_message_with_keyboard(sent_methods)
        role_callbacks = keyboard_callbacks(role_message)
        assert {
            f"{ASSIGN_ROLE_PREFIX}{target.id}:{code.value}"
            for code in SystemRoleCode
            if code is not SystemRoleCode.OWNER
        }.issubset(role_callbacks)
        assert (
            f"{ASSIGN_ROLE_PREFIX}{target.id}:OWNER"
            not in role_callbacks
        )
        back_to_profile = NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.USER_PROFILE,
            target_id=target.id,
        ).pack()
        assert back_to_profile in role_callbacks

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=admin_sender,
                data=back_to_profile,
                message_id=result_message_id,
            ),
        )
        returned_profile = last_message_with_keyboard(sent_methods)
        assert target_sender.first_name in returned_profile.text
        assert second_target_sender.first_name not in returned_profile.text
        assert (
            f"{BEGIN_ASSIGN_ROLE_PREFIX}{target.id}"
            in keyboard_callbacks(returned_profile)
        )

        async with session_factory() as session:
            first_target_role_codes = set(
                await session.scalars(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == target.id)
                )
            )
            role_assignment_audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ROLE_ASSIGNED",
                    AuditLogModel.entity_id == target.id,
                )
            )
        assert first_target_role_codes == {"ATHLETE"}
        assert role_assignment_audit_count == 0

        back_to_users = NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.USERS_LIST,
        ).pack()
        assert back_to_users in keyboard_callbacks(returned_profile)
        assert any(
            button.text == BACK_BUTTON_TEXT
            for row in returned_profile.reply_markup.inline_keyboard
            for button in row
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=admin_sender,
                data=back_to_users,
                message_id=result_message_id,
            ),
        )
        returned_list = last_message_with_keyboard(sent_methods)
        assert f"{SELECT_USER_PREFIX}{target.id}" in keyboard_callbacks(
            returned_list
        )
        assert (
            f"{SELECT_USER_PREFIX}{second_target.id}"
            in keyboard_callbacks(returned_list)
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=8,
                sender=admin_sender,
                data=f"{SELECT_USER_PREFIX}{second_target.id}",
                message_id=result_message_id,
            ),
        )
        second_profile = last_message_with_keyboard(sent_methods)
        assert second_target_sender.first_name in second_profile.text
        assert target_sender.first_name not in second_profile.text

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=9,
                sender=admin_sender,
                data=f"{BEGIN_ASSIGN_ROLE_PREFIX}{second_target.id}",
                message_id=result_message_id,
            ),
        )
        second_role_message = last_message_with_keyboard(sent_methods)
        assert (
            f"{ASSIGN_ROLE_PREFIX}{second_target.id}:"
            f"{SystemRoleCode.TRAINER.value}"
            in keyboard_callbacks(second_role_message)
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=10,
                sender=admin_sender,
                data=(
                    f"{ASSIGN_ROLE_PREFIX}{second_target.id}:"
                    f"{SystemRoleCode.TRAINER.value}"
                ),
                message_id=result_message_id,
            ),
        )
        success_message = last_message_with_keyboard(sent_methods)
        assert success_message.text.startswith(
            ROLE_ASSIGNED_TEXT.split("{")[0]
        )
        assert "ATHLETE" in success_message.text
        assert "TRAINER" in success_message.text

        async with session_factory() as session:
            second_target_role_codes = set(
                await session.scalars(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == second_target.id)
                )
            )
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "ROLE_ASSIGNED",
                    AuditLogModel.actor_user_id == administrator.id,
                    AuditLogModel.entity_id == second_target.id,
                )
            )
        assert second_target_role_codes == {"ATHLETE", "TRAINER"}
        assert audit is not None
        assert audit.payload == {"role_code": "TRAINER"}

        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=11,
                sender=second_target_sender,
                text="/menu",
            ),
        )
        target_menu_callbacks = keyboard_callbacks(
            last_message_with_keyboard(sent_methods)
        )
        assert RolePanelCallback(
            role=RolePanel.ATHLETE
        ).pack() in target_menu_callbacks
        assert RolePanelCallback(
            role=RolePanel.TRAINER
        ).pack() in target_menu_callbacks
        admin_sends = [
            method
            for method in sent_methods
            if isinstance(method, SendPhoto)
            and method.chat_id == admin_telegram_id
        ]
        assert len(admin_sends) == 2
        assert all(
            method.message_id == result_message_id
            for method in sent_methods
            if isinstance(method, (EditMessageCaption, EditMessageMedia))
            and method.chat_id == admin_telegram_id
        )
        admin_storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=admin_sender.id,
            user_id=admin_sender.id,
        )
        admin_state_data = await dispatcher.storage.get_data(admin_storage_key)
        assert (
            admin_state_data["ui_context"]["active_message"]["message_id"]
            == result_message_id
        )
        expected_active_role = (
            RolePanel.OWNER.value
            if administrative_role is SystemRoleCode.OWNER
            else RolePanel.ADMINISTRATOR.value
        )
        assert (
            admin_state_data["ui_context"]["navigation"]["active_role"]
            == expected_active_role
        )
        first_answer = next(
            method
            for method in sent_methods
            if isinstance(method, AnswerCallbackQuery)
        )
        first_edit = next(
            method
            for method in sent_methods
            if isinstance(method, EditMessageCaption)
        )
        assert sent_methods.index(first_answer) < sent_methods.index(first_edit)
    finally:
        await container.close()


async def test_stale_user_callback_returns_controlled_menu_path(
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
        return telegram_method_result(method, message_id=len(sent_methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    suffix = uuid4().hex[:8]
    admin_sender = telegram_user(
        25_000_000 + uuid4().int % 1_000_000_000,
        first_name="Admin",
        username=f"stale_admin_{suffix}",
    )
    target_sender = telegram_user(
        26_000_000 + uuid4().int % 1_000_000_000,
        first_name=f"Stale{suffix}",
        username=f"stale_target_{suffix}",
    )

    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        async with session_factory.begin() as session:
            await add_user_with_role(
                session,
                telegram_id=admin_sender.id,
                username=admin_sender.username or "",
                first_name=admin_sender.first_name,
                role_code=SystemRoleCode.ADMINISTRATOR,
            )
            target = await add_user_with_role(
                session,
                telegram_id=target_sender.id,
                username=target_sender.username or "",
                first_name=target_sender.first_name,
                role_code=SystemRoleCode.ATHLETE,
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=admin_sender, text="/menu"),
        )
        menu_screen = next(
            method for method in sent_methods if isinstance(method, SendPhoto)
        )
        menu_message_id = sent_message_id(sent_methods, menu_screen)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=admin_sender,
                data=MANAGE_USERS_ACTION,
                message_id=menu_message_id,
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
        result_screen = next(
            method
            for method in sent_methods
            if isinstance(method, SendPhoto) and method is not menu_screen
        )
        result_message_id = sent_message_id(sent_methods, result_screen)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=admin_sender,
                data=f"{SELECT_USER_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=admin_sender,
                data=f"{BEGIN_ASSIGN_ROLE_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )

        async with session_factory.begin() as session:
            await session.execute(
                delete(UserRoleModel).where(
                    UserRoleModel.user_id == target.id
                )
            )
            await session.execute(
                delete(UserModel).where(UserModel.id == target.id)
            )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=admin_sender,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.USER_PROFILE,
                    target_id=target.id,
                ).pack(),
                message_id=result_message_id,
            ),
        )
        unavailable_message = last_message_with_keyboard(sent_methods)
        assert unavailable_message.text == USER_SELECTION_UNAVAILABLE_TEXT

        menu_callback = NavigationCallback(
            action=NavigationAction.BACK,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        assert menu_callback in keyboard_callbacks(unavailable_message)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=admin_sender,
                data=menu_callback,
                message_id=result_message_id,
            ),
        )
        assert (
            last_message_with_keyboard(sent_methods).text
            == (
                "Меню администратора\n\nДобавляйте спортсменов, "
                "связывайте их с Telegram и "
                "управляйте ролями пользователей."
            )
        )
    finally:
        await container.close()


async def test_administrator_removes_role_through_telegram_flow(
    integration_settings: Settings,
    monkeypatch: Any,
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
    suffix = uuid4().hex[:8]
    admin_sender = telegram_user(
        27_000_000 + uuid4().int % 1_000_000_000,
        first_name="Admin",
        username=f"remove_admin_{suffix}",
    )
    target_sender = telegram_user(
        28_000_000 + uuid4().int % 1_000_000_000,
        first_name=f"RemoveTarget{suffix}",
        username=f"remove_target_{suffix}",
    )
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        async with session_factory.begin() as session:
            administrator = await add_user_with_role(
                session,
                telegram_id=admin_sender.id,
                username=admin_sender.username or "",
                first_name=admin_sender.first_name,
                role_code=SystemRoleCode.ADMINISTRATOR,
            )
            target = await add_user_with_role(
                session,
                telegram_id=target_sender.id,
                username=target_sender.username or "",
                first_name=target_sender.first_name,
                role_code=SystemRoleCode.ATHLETE,
            )
            trainer_role = await role(session, SystemRoleCode.TRAINER)
            owner_role = await role(session, SystemRoleCode.OWNER)
            session.add(
                UserRoleModel(
                    user_id=target.id,
                    role_id=trainer_role.id,
                    assigned_by_user_id=administrator.id,
                    assigned_at=NOW,
                )
            )
            session.add(
                UserRoleModel(
                    user_id=target.id,
                    role_id=owner_role.id,
                    assigned_by_user_id=None,
                    assigned_at=NOW,
                )
            )

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=admin_sender, text="/menu"),
        )
        menu_screen = next(
            method for method in methods if isinstance(method, SendPhoto)
        )
        menu_message_id = sent_message_id(methods, menu_screen)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=admin_sender,
                data=MANAGE_USERS_ACTION,
                message_id=menu_message_id,
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
        result_screen = next(
            method
            for method in methods
            if isinstance(method, SendPhoto) and method is not menu_screen
        )
        result_message_id = sent_message_id(methods, result_screen)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=admin_sender,
                data=f"{SELECT_USER_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )
        profile = last_message_with_keyboard(methods)
        assert (
            f"{BEGIN_REMOVE_ROLE_PREFIX}{target.id}"
            in keyboard_callbacks(profile)
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=admin_sender,
                data=f"{BEGIN_REMOVE_ROLE_PREFIX}{target.id}",
                message_id=result_message_id,
            ),
        )
        selection = last_message_with_keyboard(methods)
        selection_callbacks = keyboard_callbacks(selection)
        assert (
            f"{REMOVE_ROLE_PREFIX}{target.id}:ATHLETE"
            in selection_callbacks
        )
        assert (
            f"{REMOVE_ROLE_PREFIX}{target.id}:TRAINER"
            in selection_callbacks
        )
        assert not any(
            callback is not None and callback.endswith(":ADMINISTRATOR")
            for callback in selection_callbacks
        )
        assert not any(
            callback is not None and callback.endswith(":OWNER")
            for callback in selection_callbacks
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=admin_sender,
                data=f"{REMOVE_ROLE_PREFIX}{target.id}:TRAINER",
                message_id=result_message_id,
            ),
        )
        updated_profile = last_message_with_keyboard(methods)
        assert updated_profile.text.startswith(
            ROLE_REMOVED_TEXT.format(role="TRAINER")
        )
        assert "ATHLETE" in updated_profile.text
        assert "OWNER" in updated_profile.text
        assert "TRAINER" not in updated_profile.text.split(
            "Текущие роли:\n", maxsplit=1
        )[-1]
        assert (
            f"{BEGIN_REMOVE_ROLE_PREFIX}{target.id}"
            in keyboard_callbacks(updated_profile)
        )
        assert (
            f"{BEGIN_ASSIGN_ROLE_PREFIX}{target.id}"
            in keyboard_callbacks(updated_profile)
        )

        async with session_factory() as session:
            role_codes = set(
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
                    AuditLogModel.action == "ROLE_REMOVED",
                    AuditLogModel.actor_user_id == administrator.id,
                    AuditLogModel.entity_id == target.id,
                )
            )
        assert role_codes == {"ATHLETE", "OWNER"}
        assert audit is not None
        assert audit.payload == {"role_code": "TRAINER"}
        assert audit.created_at is not None
    finally:
        await container.close()
