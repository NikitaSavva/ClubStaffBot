from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageCaption,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User
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
    ENTER_BIRTH_DATE_TEXT,
    ENTER_FIRST_NAME_TEXT,
    ENTER_LAST_NAME_TEXT,
    INVALID_BIRTH_DATE_TEXT,
    INVALID_FIRST_NAME_TEXT,
    INVALID_LAST_NAME_TEXT,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.states import CreateAthleteStates
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
BIRTH_DATE = date(1993, 8, 25)
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
                caption="UI screen",
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
            username=f"manual_admin_{telegram_id}",
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


def last_sent_photo(methods: list[TelegramMethod[Any]]) -> SendPhoto:
    return next(
        method
        for method in reversed(methods)
        if isinstance(method, SendPhoto)
    )


def last_sent_message(methods: list[TelegramMethod[Any]]) -> SendMessage:
    return next(
        method
        for method in reversed(methods)
        if isinstance(method, SendMessage)
    )


def sent_message_id(
    methods: list[TelegramMethod[Any]],
    target: TelegramMethod[Any],
) -> int:
    return next(
        index
        for index, method in enumerate(methods, start=1)
        if method is target
    )


async def test_administrator_completes_manual_athlete_form_and_confirms(
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
    sender = telegram_user(16_000_000 + uuid4().int % 1_000_000_000)
    first_name = f"Иван{uuid4().hex[:6]}"
    last_name = "Иванов"
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        actor_user_id = await add_user_with_role(
            session_factory,
            telegram_id=sender.id,
            role_code=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )

        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        original_home = last_sent_photo(methods)
        original_home_message_id = sent_message_id(methods, original_home)

        begin_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                message_id=original_home_message_id,
            ),
        )
        begin_methods = methods[begin_offset:]
        begin_answer = next(
            item for item in begin_methods if isinstance(item, AnswerCallbackQuery)
        )
        first_name_prompt = next(
            item for item in begin_methods if isinstance(item, SendMessage)
        )
        first_name_prompt_id = sent_message_id(methods, first_name_prompt)
        assert begin_methods.index(begin_answer) < begin_methods.index(
            first_name_prompt
        )
        assert original_home.reply_markup is not None
        assert first_name_prompt.text == ENTER_FIRST_NAME_TEXT
        assert first_name_prompt_id != original_home_message_id
        assert not any(
            isinstance(item, (EditMessageCaption, EditMessageText))
            for item in begin_methods
        )

        stale_home_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=20,
                sender=sender,
                message_id=original_home_message_id,
            ),
        )
        stale_home_methods = methods[stale_home_offset:]
        assert len(stale_home_methods) == 1
        stale_home_answer = stale_home_methods[0]
        assert isinstance(stale_home_answer, AnswerCallbackQuery)
        assert stale_home_answer.text == STALE_SCREEN_TEXT
        assert await dispatcher.storage.get_state(storage_key) == (
            CreateAthleteStates.waiting_for_first_name.state
        )
        stale_home_data = await dispatcher.storage.get_data(storage_key)
        assert stale_home_data["ui_context"]["active_message"][
            "message_id"
        ] == first_name_prompt_id

        invalid_first_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text="   "),
        )
        invalid_first_methods = methods[invalid_first_offset:]
        assert not any(
            isinstance(item, DeleteMessage) for item in invalid_first_methods
        )
        invalid_first_screen = last_sent_message(methods)
        assert invalid_first_screen.text == INVALID_FIRST_NAME_TEXT

        first_name_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=4, sender=sender, text=first_name),
        )
        first_name_methods = methods[first_name_offset:]
        first_name_delete = next(
            item for item in first_name_methods if isinstance(item, DeleteMessage)
        )
        assert first_name_delete.message_id == 4
        surname_prompt = last_sent_message(methods)
        assert surname_prompt.text == ENTER_LAST_NAME_TEXT.format(
            first_name=first_name
        )
        assert first_name_prompt.reply_markup is not None
        assert surname_prompt.reply_markup is not None

        invalid_last_name_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=5, sender=sender, text="   "),
        )
        invalid_last_name_methods = methods[invalid_last_name_offset:]
        assert not any(
            isinstance(item, DeleteMessage)
            for item in invalid_last_name_methods
        )
        assert last_sent_message(methods).text == INVALID_LAST_NAME_TEXT.format(
            first_name=first_name
        )

        last_name_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=6, sender=sender, text=last_name),
        )
        last_name_methods = methods[last_name_offset:]
        last_name_delete = next(
            item for item in last_name_methods if isinstance(item, DeleteMessage)
        )
        assert last_name_delete.message_id == 6
        assert last_sent_message(methods).text == ENTER_BIRTH_DATE_TEXT.format(
            first_name=first_name,
            last_name=last_name,
        )

        for update_id, invalid_date in enumerate(
            ("1993-08-25", "25/08/1993", "31.02.2000", "abc"),
            start=7,
        ):
            invalid_date_offset = len(methods)
            await dispatcher.feed_update(
                bot,
                message_update(
                    update_id=update_id,
                    sender=sender,
                    text=invalid_date,
                ),
            )
            invalid_date_methods = methods[invalid_date_offset:]
            assert not any(
                isinstance(item, DeleteMessage) for item in invalid_date_methods
            )
            assert last_sent_message(
                methods
            ).text == INVALID_BIRTH_DATE_TEXT.format(
                first_name=first_name,
                last_name=last_name,
            )

        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_birth_date.state
        )
        async with session_factory() as session:
            athlete_before_confirmation = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
        assert athlete_before_confirmation is None

        await dispatcher.feed_update(
            bot,
            message_update(
                update_id=11,
                sender=sender,
                text="25.08.1993",
            ),
        )
        confirmation = last_sent_message(methods)
        confirmation_message_id = sent_message_id(methods, confirmation)
        assert confirmation.text == CONFIRM_CREATE_ATHLETE_TEXT.format(
            first_name=first_name,
            last_name=last_name,
            birth_date="25.08.1993",
        )
        state_data = await dispatcher.storage.get_data(storage_key)
        assert state_data["flow_context"] == {
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": "1993-08-25",
        }
        assert (
            await dispatcher.storage.get_state(storage_key)
            == CreateAthleteStates.waiting_for_confirmation.state
        )

        confirm_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=12,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
                message_id=confirmation_message_id,
            ),
        )
        confirm_methods = methods[confirm_offset:]
        answer = next(
            item
            for item in confirm_methods
            if isinstance(item, AnswerCallbackQuery)
        )
        success = next(
            item for item in confirm_methods if isinstance(item, SendPhoto)
        )
        success_message_id = sent_message_id(methods, success)
        assert confirm_methods.index(answer) < confirm_methods.index(success)
        assert confirmation.reply_markup is not None
        assert success.caption == CREATE_ATHLETE_SUCCESS_TEXT.format(
            first_name=first_name,
            last_name=last_name,
            birth_date="25.08.1993",
        )
        assert success.photo == "admin-banner-file-id"
        assert await dispatcher.storage.get_state(storage_key) is None
        assert "flow_context" not in await dispatcher.storage.get_data(
            storage_key
        )

        stale_confirm_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=13,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
                message_id=confirmation_message_id,
            ),
        )
        stale_confirm_methods = methods[stale_confirm_offset:]
        assert len(stale_confirm_methods) == 1
        stale_answer = stale_confirm_methods[0]
        assert isinstance(stale_answer, AnswerCallbackQuery)
        assert stale_answer.text == STALE_SCREEN_TEXT

        panel_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=14,
                sender=sender,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.ROLE_PANEL,
                ).pack(),
                message_id=success_message_id,
            ),
        )
        panel_methods = methods[panel_offset:]
        panel_answer = next(
            item for item in panel_methods if isinstance(item, AnswerCallbackQuery)
        )
        new_home = next(
            item for item in panel_methods if isinstance(item, SendPhoto)
        )
        new_home_message_id = sent_message_id(methods, new_home)
        assert panel_methods.index(panel_answer) < panel_methods.index(new_home)
        assert success.reply_markup is not None
        assert new_home_message_id != original_home_message_id

        active_data = await dispatcher.storage.get_data(storage_key)
        assert active_data["ui_context"]["active_message"]["message_id"] == (
            new_home_message_id
        )

        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
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
        assert athlete.last_name == last_name
        assert athlete.birth_date == BIRTH_DATE
        assert audit is not None
        assert audit.entity_id == athlete.id
    finally:
        await container.close()


async def test_back_moves_through_manual_athlete_steps_without_write(
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
    sender = telegram_user(17_000_000 + uuid4().int % 1_000_000_000)
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        home_message_id = sent_message_id(methods, last_sent_photo(methods))
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                message_id=home_message_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text="Иван"),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=4, sender=sender, text="Иванов"),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=5, sender=sender, text="25.08.1993"),
        )
        active_form_message_id = sent_message_id(
            methods,
            last_sent_message(methods),
        )

        back_steps = (
            (
                NavigationTarget.CREATE_ATHLETE_BIRTH_DATE,
                ENTER_BIRTH_DATE_TEXT.format(
                    first_name="Иван",
                    last_name="Иванов",
                ),
                CreateAthleteStates.waiting_for_birth_date.state,
            ),
            (
                NavigationTarget.CREATE_ATHLETE_LAST_NAME,
                ENTER_LAST_NAME_TEXT.format(first_name="Иван"),
                CreateAthleteStates.waiting_for_last_name.state,
            ),
            (
                NavigationTarget.CREATE_ATHLETE_FIRST_NAME,
                ENTER_FIRST_NAME_TEXT,
                CreateAthleteStates.waiting_for_first_name.state,
            ),
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        for update_id, (target, expected_text, expected_state) in enumerate(
            back_steps,
            start=6,
        ):
            offset = len(methods)
            await dispatcher.feed_update(
                bot,
                callback_update(
                    update_id=update_id,
                    sender=sender,
                    data=NavigationCallback(
                        action=NavigationAction.BACK,
                        target=target,
                    ).pack(),
                    message_id=active_form_message_id,
                ),
            )
            step_methods = methods[offset:]
            edit = next(
                item
                for item in step_methods
                if isinstance(item, EditMessageText)
            )
            assert edit.message_id == active_form_message_id
            assert edit.text == expected_text
            assert await dispatcher.storage.get_state(storage_key) == expected_state

        assert (await dispatcher.storage.get_data(storage_key))[
            "flow_context"
        ] == {}
    finally:
        await container.close()


async def test_cancelled_manual_athlete_form_creates_no_business_state(
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
    sender = telegram_user(18_000_000 + uuid4().int % 1_000_000_000)
    first_name = f"Cancelled{uuid4().hex[:6]}"
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        actor_user_id = await add_user_with_role(
            session_factory,
            telegram_id=sender.id,
            role_code=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        original_home = last_sent_photo(methods)
        original_home_message_id = sent_message_id(methods, original_home)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                message_id=original_home_message_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text=first_name),
        )
        active_form_message_id = sent_message_id(
            methods,
            last_sent_message(methods),
        )
        cancel_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=sender,
                data=NavigationCallback(
                    action=NavigationAction.CANCEL,
                    target=NavigationTarget.ROLE_PANEL,
                ).pack(),
                message_id=active_form_message_id,
            ),
        )

        cancel_methods = methods[cancel_offset:]
        cancel_answer = next(
            item for item in cancel_methods if isinstance(item, AnswerCallbackQuery)
        )
        new_home = next(
            item for item in cancel_methods if isinstance(item, SendPhoto)
        )
        assert cancel_methods.index(cancel_answer) < cancel_methods.index(new_home)
        assert original_home.reply_markup is not None
        assert last_sent_message(methods[:cancel_offset]).reply_markup is not None
        assert CREATE_ATHLETE_CANCELLED_TEXT in (new_home.caption or "")
        assert sent_message_id(methods, new_home) != original_home_message_id
        assert not any(
            isinstance(item, (EditMessageCaption, EditMessageText))
            for item in cancel_methods
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        assert await dispatcher.storage.get_state(storage_key) is None
        assert "flow_context" not in await dispatcher.storage.get_data(
            storage_key
        )

        async with session_factory() as session:
            athlete_count = await session.scalar(
                select(func.count())
                .select_from(AthleteModel)
                .where(AthleteModel.first_name == first_name)
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "ATHLETE_CREATED_MANUALLY",
                    AuditLogModel.actor_user_id == actor_user_id,
                )
            )
        assert athlete_count == 0
        assert audit_count == 0
    finally:
        await container.close()


async def test_valid_input_delete_failure_does_not_interrupt_form(
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
        if isinstance(method, DeleteMessage):
            raise TelegramBadRequest(
                method=method,
                message="message to delete not found",
            )
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    sender = telegram_user(18_500_000 + uuid4().int % 1_000_000_000)
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        home_message_id = sent_message_id(methods, last_sent_photo(methods))
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                message_id=home_message_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text="Иван"),
        )

        assert any(isinstance(item, DeleteMessage) for item in methods)
        assert last_sent_message(methods).text == ENTER_LAST_NAME_TEXT.format(
            first_name="Иван"
        )
        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
        )
        assert await dispatcher.storage.get_state(storage_key) == (
            CreateAthleteStates.waiting_for_last_name.state
        )
        assert (await dispatcher.storage.get_data(storage_key))[
            "flow_context"
        ] == {"first_name": "Иван"}
    finally:
        await container.close()


@pytest.mark.parametrize(
    "role_code",
    [SystemRoleCode.ATHLETE, SystemRoleCode.TRAINER],
)
async def test_non_administrator_cannot_confirm_manual_athlete(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    role_code: SystemRoleCode,
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
    sender = telegram_user(19_000_000 + uuid4().int % 1_000_000_000)
    first_name = f"Forbidden{uuid4().hex[:6]}"
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        await add_user_with_role(
            session_factory,
            telegram_id=sender.id,
            role_code=role_code,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            message_update(update_id=1, sender=sender, text="/menu"),
        )
        home_message_id = sent_message_id(methods, last_sent_photo(methods))
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=sender,
                message_id=home_message_id,
            ),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text=first_name),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=4, sender=sender, text="Иванов"),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=5, sender=sender, text="25.08.1993"),
        )
        confirmation_message_id = sent_message_id(
            methods,
            last_sent_message(methods),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
                message_id=confirmation_message_id,
            ),
        )

        assert any(
            isinstance(item, SendPhoto)
            and item.caption == CREATE_ATHLETE_PERMISSION_DENIED_TEXT
            for item in methods
        )
        async with session_factory() as session:
            athlete = await session.scalar(
                select(AthleteModel).where(
                    AthleteModel.first_name == first_name
                )
            )
        assert athlete is None
    finally:
        await container.close()
