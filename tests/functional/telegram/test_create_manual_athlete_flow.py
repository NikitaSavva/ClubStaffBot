from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
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

        await dispatcher.feed_update(
            bot,
            callback_update(update_id=1, sender=sender),
        )
        assert last_sent_photo(methods).caption == ENTER_FIRST_NAME_TEXT

        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text="   "),
        )
        assert last_sent_photo(methods).caption == INVALID_FIRST_NAME_TEXT

        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text=first_name),
        )
        assert last_sent_photo(methods).caption == ENTER_LAST_NAME_TEXT

        await dispatcher.feed_update(
            bot,
            message_update(update_id=4, sender=sender, text="   "),
        )
        assert last_sent_photo(methods).caption == INVALID_LAST_NAME_TEXT

        await dispatcher.feed_update(
            bot,
            message_update(update_id=5, sender=sender, text=last_name),
        )
        assert last_sent_photo(methods).caption == ENTER_BIRTH_DATE_TEXT

        for update_id, invalid_date in enumerate(
            ("1993-08-25", "25/08/1993", "31.02.2000", "abc"),
            start=6,
        ):
            await dispatcher.feed_update(
                bot,
                message_update(
                    update_id=update_id,
                    sender=sender,
                    text=invalid_date,
                ),
            )
            assert last_sent_photo(methods).caption == INVALID_BIRTH_DATE_TEXT

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=sender.id,
            user_id=sender.id,
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
                update_id=10,
                sender=sender,
                text="25.08.1993",
            ),
        )
        confirmation = last_sent_photo(methods)
        assert confirmation.caption == CONFIRM_CREATE_ATHLETE_TEXT.format(
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
                update_id=11,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        )
        confirm_methods = methods[confirm_offset:]
        answer = next(
            item
            for item in confirm_methods
            if isinstance(item, AnswerCallbackQuery)
        )
        success = next(
            item
            for item in confirm_methods
            if isinstance(item, EditMessageCaption)
        )
        assert confirm_methods.index(answer) < confirm_methods.index(success)
        assert success.caption == CREATE_ATHLETE_SUCCESS_TEXT.format(
            first_name=first_name,
            last_name=last_name,
        )
        assert await dispatcher.storage.get_state(storage_key) is None
        assert "flow_context" not in await dispatcher.storage.get_data(
            storage_key
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
            callback_update(update_id=1, sender=sender),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text="Иван"),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=3, sender=sender, text="Иванов"),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=4, sender=sender, text="25.08.1993"),
        )

        back_steps = (
            (
                NavigationTarget.CREATE_ATHLETE_BIRTH_DATE,
                ENTER_BIRTH_DATE_TEXT,
                CreateAthleteStates.waiting_for_birth_date.state,
            ),
            (
                NavigationTarget.CREATE_ATHLETE_LAST_NAME,
                ENTER_LAST_NAME_TEXT,
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
            start=5,
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
                ),
            )
            step_methods = methods[offset:]
            edit = next(
                item
                for item in step_methods
                if isinstance(item, EditMessageCaption)
            )
            assert edit.caption == expected_text
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
            callback_update(update_id=1, sender=sender),
        )
        await dispatcher.feed_update(
            bot,
            message_update(update_id=2, sender=sender, text=first_name),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=sender,
                data=NavigationCallback(
                    action=NavigationAction.CANCEL,
                    target=NavigationTarget.ROLE_PANEL,
                ).pack(),
            ),
        )

        assert any(
            isinstance(item, EditMessageCaption)
            and item.caption is not None
            and CREATE_ATHLETE_CANCELLED_TEXT in item.caption
            for item in methods
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
        for update in (
            callback_update(update_id=1, sender=sender),
            message_update(update_id=2, sender=sender, text=first_name),
            message_update(update_id=3, sender=sender, text="Иванов"),
            message_update(update_id=4, sender=sender, text="25.08.1993"),
            callback_update(
                update_id=5,
                sender=sender,
                data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        ):
            await dispatcher.feed_update(bot, update)

        assert any(
            isinstance(item, EditMessageCaption)
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
