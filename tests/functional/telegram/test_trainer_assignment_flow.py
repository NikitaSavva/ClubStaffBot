from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageCaption,
    EditMessageMedia,
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
from domain.club import TrainingGroupType
from domain.identity import SystemRoleCode
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import (
    AuditLogModel,
    GroupNameModel,
    RoleModel,
    ScheduleRuleModel,
    SportDirectionModel,
    TrainingGroupModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.trainer_assignment import (
    ASSIGN_TRAINER_ACTION,
    CONFIRM_ASSIGN_TRAINER_ACTION,
    SELECT_GROUP_PREFIX,
    SELECT_TRAINER_PREFIX,
)
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


@dataclass(frozen=True, slots=True)
class FlowData:
    actor: User
    actor_user_id: int
    trainer_user_id: int
    athlete_user_id: int
    free_group_id: int
    duplicate_group_id: int
    assigned_group_id: int


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup


def callback_update(
    *,
    update_id: int,
    sender: User,
    data: str,
    message_id: int,
) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=sender,
            chat_instance=f"chat-{sender.id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=NOW,
                chat=Chat(id=sender.id, type=ChatType.PRIVATE),
                from_user=BOT_USER,
                text="Trainer assignment",
            ),
        ),
    )


def command_update(*, update_id: int, sender: User, text: str) -> Update:
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


def last_screen(methods: list[TelegramMethod[Any]]) -> ScreenSnapshot:
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
    raise AssertionError("No rendered screen with keyboard")


def callback_texts(screen: ScreenSnapshot) -> dict[str, str]:
    return {
        button.callback_data: button.text
        for row in screen.reply_markup.inline_keyboard
        for button in row
        if button.callback_data is not None
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


async def role(
    session: AsyncSession,
    role_code: SystemRoleCode,
) -> RoleModel:
    result = await session.scalar(
        select(RoleModel).where(RoleModel.code == role_code.value)
    )
    assert result is not None
    return result


async def add_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    first_name: str,
    role_codes: tuple[SystemRoleCode, ...],
) -> UserModel:
    suffix = uuid4().hex[:8]
    user = UserModel(
        telegram_id=telegram_id,
        username=f"{first_name.lower()}_{suffix}",
        first_name=first_name,
        last_name="User",
        is_active=True,
        registered_at=NOW,
        last_seen_at=NOW,
    )
    session.add(user)
    await session.flush()
    for role_code in role_codes:
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


async def add_group(
    session: AsyncSession,
    *,
    direction_id: int,
    name_id: int,
    weekdays: tuple[int, ...],
    starts_at: time,
    ends_at: time,
    trainer_id: int | None,
) -> TrainingGroupModel:
    group = TrainingGroupModel(
        direction_id=direction_id,
        trainer_id=trainer_id,
        name_id=name_id,
        group_type=TrainingGroupType.REGULAR,
        is_active=True,
    )
    session.add(group)
    await session.flush()
    session.add_all(
        [
            ScheduleRuleModel(
                group_id=group.id,
                weekday=weekday,
                start_time=starts_at,
                end_time=ends_at,
                valid_from=None,
                valid_until=None,
                is_active=True,
            )
            for weekday in weekdays
        ]
    )
    return group


async def arrange_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    administrative_role: SystemRoleCode,
) -> FlowData:
    actor_telegram_id = 71_000_000 + uuid4().int % 1_000_000_000
    actor = User(
        id=actor_telegram_id,
        is_bot=False,
        first_name="Admin",
        last_name="User",
        username=f"admin_{uuid4().hex[:8]}",
    )
    async with session_factory.begin() as session:
        actor_model = await add_user(
            session,
            telegram_id=actor_telegram_id,
            first_name="Admin",
            role_codes=(administrative_role,),
        )
        trainer = await add_user(
            session,
            telegram_id=actor_telegram_id + 1,
            first_name="Иван",
            role_codes=(
                SystemRoleCode.ATHLETE,
                SystemRoleCode.TRAINER,
            ),
        )
        athlete = await add_user(
            session,
            telegram_id=actor_telegram_id + 2,
            first_name="НеТренер",
            role_codes=(SystemRoleCode.ATHLETE,),
        )
        direction = await session.scalar(
            select(SportDirectionModel).where(
                SportDirectionModel.name == "Кикбоксинг"
            )
        )
        group_name = await session.scalar(
            select(GroupNameModel).where(GroupNameModel.name == "Взрослые")
        )
        girls_name = await session.scalar(
            select(GroupNameModel).where(GroupNameModel.name == "Девушки")
        )
        assert direction is not None
        assert group_name is not None
        assert girls_name is not None
        free_group = await add_group(
            session,
            direction_id=direction.id,
            name_id=group_name.id,
            weekdays=(0, 2, 4),
            starts_at=time(19, 0),
            ends_at=time(20, 30),
            trainer_id=None,
        )
        duplicate_group = await add_group(
            session,
            direction_id=direction.id,
            name_id=group_name.id,
            weekdays=(1, 3, 5),
            starts_at=time(8, 30),
            ends_at=time(10, 0),
            trainer_id=None,
        )
        assigned_group = await add_group(
            session,
            direction_id=direction.id,
            name_id=girls_name.id,
            weekdays=(1, 3),
            starts_at=time(10, 0),
            ends_at=time(11, 0),
            trainer_id=trainer.id,
        )
    return FlowData(
        actor=actor,
        actor_user_id=actor_model.id,
        trainer_user_id=trainer.id,
        athlete_user_id=athlete.id,
        free_group_id=free_group.id,
        duplicate_group_id=duplicate_group.id,
        assigned_group_id=assigned_group.id,
    )


async def cleanup_flow_data(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    group_ids = (
        data.free_group_id,
        data.duplicate_group_id,
        data.assigned_group_id,
    )
    user_ids = (
        data.actor_user_id,
        data.trainer_user_id,
        data.athlete_user_id,
    )
    async with session_factory.begin() as session:
        await session.execute(
            delete(AuditLogModel).where(
                AuditLogModel.entity_type == "TRAINING_GROUP",
                AuditLogModel.entity_id.in_(group_ids),
            )
        )
        await session.execute(
            delete(ScheduleRuleModel).where(
                ScheduleRuleModel.group_id.in_(group_ids)
            )
        )
        await session.execute(
            delete(TrainingGroupModel).where(
                TrainingGroupModel.id.in_(group_ids)
            )
        )
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id.in_(user_ids))
        )
        await session.execute(
            delete(UserModel).where(UserModel.id.in_(user_ids))
        )


async def open_confirmation(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
) -> int:
    await dispatcher.feed_update(
        bot,
        command_update(update_id=1, sender=data.actor, text="/menu"),
    )
    menu = next(method for method in methods if isinstance(method, SendPhoto))
    menu_id = sent_message_id(methods, menu)

    entry_offset = len(methods)
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=2,
            sender=data.actor,
            data=ASSIGN_TRAINER_ACTION,
            message_id=menu_id,
        ),
    )
    entry_methods = methods[entry_offset:]
    group_screen_method = next(
        method for method in entry_methods if isinstance(method, SendPhoto)
    )
    assert not any(
        isinstance(method, (EditMessageCaption, EditMessageMedia))
        for method in entry_methods
    )
    group_screen_id = sent_message_id(methods, group_screen_method)
    group_screen = last_screen(methods)
    group_buttons = callback_texts(group_screen)
    assert group_buttons[f"{SELECT_GROUP_PREFIX}{data.free_group_id}"] == (
        "K1 · Взрослые — ПН/СР/ПТ 19:00"
    )
    assert group_buttons[
        f"{SELECT_GROUP_PREFIX}{data.duplicate_group_id}"
    ] == "K1 · Взрослые — ВТ/ЧТ/СБ 08:30"
    assert group_buttons[
        f"{SELECT_GROUP_PREFIX}{data.assigned_group_id}"
    ] == "✓ K1 · Девушки — ВТ/ЧТ 10:00"
    assert group_screen.text == "Назначение тренера\n\nВыберите группу:"
    assert all(
        detail not in group_screen.text
        for detail in (
            "Кикбоксинг",
            "Взрослые",
            "Девушки",
            "ПН/СР/ПТ",
            "19:00",
            "20:30",
            "1. ",
        )
    )

    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=3,
            sender=data.actor,
            data=f"{SELECT_GROUP_PREFIX}{data.assigned_group_id}",
            message_id=group_screen_id,
        ),
    )
    assigned_screen = last_screen(methods)
    assert "Тренер уже назначен" in assigned_screen.text
    assert CONFIRM_ASSIGN_TRAINER_ACTION not in callback_texts(assigned_screen)

    back_to_groups = NavigationCallback(
        action=NavigationAction.BACK,
        target=NavigationTarget.TRAINING_GROUPS,
    ).pack()
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=4,
            sender=data.actor,
            data=back_to_groups,
            message_id=group_screen_id,
        ),
    )
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=5,
            sender=data.actor,
            data=f"{SELECT_GROUP_PREFIX}{data.free_group_id}",
            message_id=group_screen_id,
        ),
    )
    trainer_screen = last_screen(methods)
    trainer_callbacks = callback_texts(trainer_screen)
    assert f"{SELECT_TRAINER_PREFIX}{data.trainer_user_id}" in trainer_callbacks
    assert f"{SELECT_TRAINER_PREFIX}{data.athlete_user_id}" not in trainer_callbacks

    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=6,
            sender=data.actor,
            data=f"{SELECT_TRAINER_PREFIX}{data.trainer_user_id}",
            message_id=group_screen_id,
        ),
    )
    confirmation = last_screen(methods)
    assert confirmation.text.startswith("Назначить тренера?")
    assert "Кикбоксинг · Взрослые" in confirmation.text
    assert "ПН/СР/ПТ 19:00–20:30" in confirmation.text
    assert "Иван User" in confirmation.text
    assert CONFIRM_ASSIGN_TRAINER_ACTION in callback_texts(confirmation)
    return group_screen_id


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_administrator_and_owner_assign_trainer_through_shared_flow(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    administrative_role: SystemRoleCode,
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
    session_factory: async_sessionmaker[AsyncSession] | None = None
    data: FlowData | None = None
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=administrative_role,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_message_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=data.actor,
                data=CONFIRM_ASSIGN_TRAINER_ACTION,
                message_id=confirmation_message_id,
            ),
        )
        success = last_screen(methods)
        assert success.text.startswith("Тренер назначен")
        assert "Иван User" in success.text

        async with session_factory() as session:
            trainer_id = await session.scalar(
                select(TrainingGroupModel.trainer_id).where(
                    TrainingGroupModel.id == data.free_group_id
                )
            )
            audits = (
                await session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "TRAINER_ASSIGNED",
                        AuditLogModel.entity_id == data.free_group_id,
                    )
                )
            ).all()
        assert trainer_id == data.trainer_user_id
        assert len(audits) == 1
        assert audits[0].actor_user_id == data.actor_user_id
        assert audits[0].payload == {
            "trainer_user_id": data.trainer_user_id
        }
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_cancel_sends_new_home_and_stale_confirmation_cannot_write(
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
    session_factory: async_sessionmaker[AsyncSession] | None = None
    data: FlowData | None = None
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        confirmation_message_id = await open_confirmation(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
        )

        cancel = NavigationCallback(
            action=NavigationAction.CANCEL,
            target=NavigationTarget.ROLE_PANEL,
        ).pack()
        cancel_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=7,
                sender=data.actor,
                data=cancel,
                message_id=confirmation_message_id,
            ),
        )
        cancel_methods = methods[cancel_offset:]
        new_home = next(
            method for method in cancel_methods if isinstance(method, SendPhoto)
        )
        new_home_id = sent_message_id(methods, new_home)
        assert new_home_id != confirmation_message_id
        assert new_home.caption is not None
        assert "Назначение тренера отменено" in new_home.caption

        stale_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=8,
                sender=data.actor,
                data=CONFIRM_ASSIGN_TRAINER_ACTION,
                message_id=confirmation_message_id,
            ),
        )
        stale_methods = methods[stale_offset:]
        assert len(stale_methods) == 1
        stale_answer = stale_methods[0]
        assert isinstance(stale_answer, AnswerCallbackQuery)
        assert stale_answer.text == STALE_SCREEN_TEXT

        storage_key = StorageKey(
            bot_id=bot.id,
            chat_id=data.actor.id,
            user_id=data.actor.id,
        )
        assert await dispatcher.storage.get_state(storage_key) is None
        state_data = await dispatcher.storage.get_data(storage_key)
        assert "flow_context" not in state_data
        assert state_data["ui_context"]["active_message"][
            "message_id"
        ] == new_home_id

        async with session_factory() as session:
            trainer_id = await session.scalar(
                select(TrainingGroupModel.trainer_id).where(
                    TrainingGroupModel.id == data.free_group_id
                )
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.action == "TRAINER_ASSIGNED",
                    AuditLogModel.entity_id == data.free_group_id,
                )
            )
        assert trainer_id is None
        assert audit_count == 0
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()
