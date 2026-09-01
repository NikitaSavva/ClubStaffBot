from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import (
    AnswerCallbackQuery,
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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionStatus
from entrypoints.bot import create_dispatcher
from infrastructure.athlete_qr import ItsDangerousAthleteQrTokenCodec
from infrastructure.database.models import (
    AthleteModel,
    RoleModel,
    SubscriptionModel,
    SubscriptionPlanModel,
    UserModel,
    UserRoleModel,
)
from presentation.telegram.handlers.athlete_qr import MY_QR_ACTION
from presentation.telegram.middlewares.active_screen import STALE_SCREEN_TEXT
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import RolePanel, RolePanelCallback
from presentation.telegram.presenters.athlete_qr import (
    ATHLETE_PROFILE_NOT_FOUND_TEXT,
    BODY,
    TITLE,
)
from tests.functional.telegram.fakes import telegram_method_result

NOW = datetime(2026, 9, 1, 10, tzinfo=UTC)
BOT_USER = User(
    id=123456789,
    is_bot=True,
    first_name="Staff Bot",
    username="staff_test_bot",
)


@dataclass(frozen=True, slots=True)
class FlowData:
    telegram_user: User
    user_id: int
    athlete_id: int | None
    athlete_public_id: UUID | None


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    text: str
    reply_markup: InlineKeyboardMarkup
    method: SendMessage | SendPhoto


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
                caption="UI screen",
            ),
        ),
    )


def last_screen(methods: list[TelegramMethod[Any]]) -> ScreenSnapshot:
    for method in reversed(methods):
        if isinstance(method, SendPhoto):
            text = method.caption
            reply_markup = method.reply_markup
        elif isinstance(method, SendMessage):
            text = method.text
            reply_markup = method.reply_markup
        else:
            continue
        if text is not None and isinstance(reply_markup, InlineKeyboardMarkup):
            return ScreenSnapshot(text, reply_markup, method)
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


async def get_role(
    session: AsyncSession,
    code: SystemRoleCode,
) -> RoleModel:
    role = await session.scalar(
        select(RoleModel).where(RoleModel.code == code.value)
    )
    assert role is not None
    return role


async def arrange_flow(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    variant: str,
    roles: tuple[SystemRoleCode, ...] = (SystemRoleCode.ATHLETE,),
) -> FlowData:
    telegram_id = 91_000_000 + uuid4().int % 1_000_000_000
    telegram_user = User(
        id=telegram_id,
        is_bot=False,
        first_name="Иван",
        last_name="Иванов",
        username=f"qr_athlete_{uuid4().hex[:8]}",
    )
    async with session_factory.begin() as session:
        user = UserModel(
            telegram_id=telegram_id,
            username=telegram_user.username,
            first_name="Иван",
            last_name="Иванов",
            is_active=True,
            registered_at=NOW,
            last_seen_at=NOW,
        )
        session.add(user)
        await session.flush()
        for code in roles:
            role = await get_role(session, code)
            session.add(
                UserRoleModel(
                    user_id=user.id,
                    role_id=role.id,
                    assigned_by_user_id=None,
                    assigned_at=NOW,
                )
            )

        if variant == "missing_profile":
            return FlowData(telegram_user, user.id, None, None)

        athlete = AthleteModel(
            user_id=user.id,
            first_name="Иван",
            last_name="Иванов",
            birth_date=None,
            phone=None,
            is_active=True,
        )
        session.add(athlete)
        await session.flush()

        if variant in {"expired_subscription", "zero_visits"}:
            plan = await session.scalar(
                select(SubscriptionPlanModel).where(
                    SubscriptionPlanModel.code == "12_VISITS"
                )
            )
            assert plan is not None
            expires_at = (
                datetime(2025, 1, 1, 12, tzinfo=UTC)
                if variant == "expired_subscription"
                else datetime(2027, 1, 1, 12, tzinfo=UTC)
            )
            session.add(
                SubscriptionModel(
                    athlete_id=athlete.id,
                    group_id=None,
                    plan_id=plan.id,
                    activated_by_user_id=user.id,
                    activated_at=datetime(2024, 12, 1, 12, tzinfo=UTC),
                    starts_at=datetime(2024, 12, 1, 12, tzinfo=UTC),
                    expires_at=expires_at,
                    activation_price=Decimal(plan.price),
                    remaining_visits=(
                        0 if variant == "zero_visits" else 7
                    ),
                    status=SubscriptionStatus.ACTIVE,
                )
            )

        return FlowData(
            telegram_user,
            user.id,
            athlete.id,
            athlete.athlete_public_id,
        )


async def cleanup_flow(
    session_factory: async_sessionmaker[AsyncSession],
    data: FlowData,
) -> None:
    async with session_factory.begin() as session:
        if data.athlete_id is not None:
            await session.execute(
                delete(SubscriptionModel).where(
                    SubscriptionModel.athlete_id == data.athlete_id
                )
            )
        await session.execute(
            delete(UserRoleModel).where(UserRoleModel.user_id == data.user_id)
        )
        if data.athlete_id is not None:
            await session.execute(
                delete(AthleteModel).where(AthleteModel.id == data.athlete_id)
            )
        await session.execute(
            delete(UserModel).where(UserModel.id == data.user_id)
        )


async def open_athlete_home(
    *,
    dispatcher: Any,
    bot: Bot,
    methods: list[TelegramMethod[Any]],
    data: FlowData,
    multi_role: bool,
) -> int:
    await dispatcher.feed_update(
        bot,
        command_update(update_id=1, sender=data.telegram_user, text="/menu"),
    )
    root = last_screen(methods)
    root_id = sent_message_id(methods, root.method)
    if not multi_role:
        assert callback_texts(root)[MY_QR_ACTION] == "Мой QR"
        return root_id

    athlete_callback = RolePanelCallback(role=RolePanel.ATHLETE).pack()
    assert athlete_callback in callback_texts(root)
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=2,
            sender=data.telegram_user,
            data=athlete_callback,
            message_id=root_id,
        ),
    )
    athlete_home = last_screen(methods)
    assert callback_texts(athlete_home)[MY_QR_ACTION] == "Мой QR"
    return sent_message_id(methods, athlete_home.method)


def install_issue_and_qr_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[UUID], list[str]]:
    issued_for: list[UUID] = []
    rendered_tokens: list[str] = []

    def fake_issue(
        self: ItsDangerousAthleteQrTokenCodec,
        athlete_public_id: UUID,
    ) -> str:
        del self
        issued_for.append(athlete_public_id)
        return f"signed-token-{len(issued_for)}"

    def fake_generate_qr_png(token: str) -> bytes:
        rendered_tokens.append(token)
        return b"in-memory-png"

    monkeypatch.setattr(ItsDangerousAthleteQrTokenCodec, "issue", fake_issue)
    monkeypatch.setattr(
        "presentation.telegram.handlers.athlete_qr.generate_qr_png",
        fake_generate_qr_png,
    )
    return issued_for, rendered_tokens


@pytest.mark.parametrize(
    "variant",
    ["no_subscription", "expired_subscription", "zero_visits"],
)
async def test_my_qr_is_independent_from_subscription_state(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    data: FlowData | None = None
    issued_for, rendered_tokens = install_issue_and_qr_spies(monkeypatch)

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(session_factory, variant=variant)
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=False,
        )

        offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.telegram_user,
                data=MY_QR_ACTION,
                message_id=home_id,
            ),
        )

        new_methods = methods[offset:]
        assert sum(
            isinstance(method, AnswerCallbackQuery)
            for method in new_methods
        ) == 1
        photos = [
            method for method in new_methods if isinstance(method, SendPhoto)
        ]
        assert len(photos) == 1
        assert isinstance(photos[0].photo, BufferedInputFile)
        assert photos[0].photo.data == b"in-memory-png"
        assert data.athlete_public_id is not None
        assert issued_for == [data.athlete_public_id]
        assert rendered_tokens == ["signed-token-1"]
        screen = last_screen(methods)
        assert screen.text == f"{TITLE}\n\n{BODY}"
        assert "signed-token" not in screen.text
        assert str(data.athlete_public_id) not in screen.text
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()


async def test_missing_athlete_does_not_issue_token_or_render_qr(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    data: FlowData | None = None
    issued_for, rendered_tokens = install_issue_and_qr_spies(monkeypatch)

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(
            session_factory,
            variant="missing_profile",
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=False,
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.telegram_user,
                data=MY_QR_ACTION,
                message_id=home_id,
            ),
        )

        assert ATHLETE_PROFILE_NOT_FOUND_TEXT in last_screen(methods).text
        assert not issued_for
        assert not rendered_tokens
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()


async def test_multi_role_return_reopen_and_stale_home_callback(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = create_container(integration_settings)
    methods: list[TelegramMethod[Any]] = []
    data: FlowData | None = None
    issued_for, rendered_tokens = install_issue_and_qr_spies(monkeypatch)

    async def fake_bot_call(
        bot: Bot,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        del bot, request_timeout
        methods.append(method)
        return telegram_method_result(method, message_id=len(methods))

    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    try:
        await bootstrap_system_roles(container)
        session_factory = await container.get(
            async_sessionmaker[AsyncSession]
        )
        data = await arrange_flow(
            session_factory,
            variant="no_subscription",
            roles=(SystemRoleCode.OWNER, SystemRoleCode.ATHLETE),
        )
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        athlete_home_id = await open_athlete_home(
            dispatcher=dispatcher,
            bot=bot,
            methods=methods,
            data=data,
            multi_role=True,
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.telegram_user,
                data=MY_QR_ACTION,
                message_id=athlete_home_id,
            ),
        )
        first_qr = last_screen(methods)
        first_qr_id = sent_message_id(methods, first_qr.method)
        assert len(issued_for) == 1

        stale_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=4,
                sender=data.telegram_user,
                data=MY_QR_ACTION,
                message_id=athlete_home_id,
            ),
        )
        stale_methods = methods[stale_offset:]
        assert len(stale_methods) == 1
        assert isinstance(stale_methods[0], AnswerCallbackQuery)
        assert stale_methods[0].text == STALE_SCREEN_TEXT
        assert len(issued_for) == 1

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=5,
                sender=data.telegram_user,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.ROLE_PANEL,
                ).pack(),
                message_id=first_qr_id,
            ),
        )
        athlete_home = last_screen(methods)
        assert athlete_home.text.startswith("Показывайте свой QR-код")
        assert MY_QR_ACTION in callback_texts(athlete_home)
        new_home_id = sent_message_id(methods, athlete_home.method)

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=6,
                sender=data.telegram_user,
                data=MY_QR_ACTION,
                message_id=new_home_id,
            ),
        )

        assert len(issued_for) == 2
        assert rendered_tokens == ["signed-token-1", "signed-token-2"]
        assert sum(
            isinstance(method, SendPhoto)
            and method.caption == f"{TITLE}\n\n{BODY}"
            for method in methods
        ) == 2
    finally:
        if data is not None:
            await cleanup_flow(session_factory, data)
        await container.close()
