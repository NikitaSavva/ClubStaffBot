from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User
from sqlalchemy import select

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.development import create_development_invite
from bootstrap.startup import bootstrap_system_roles
from entrypoints.bot import create_dispatcher, run_bot
from infrastructure.database.models import (
    AthleteModel,
    AuditLogModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from infrastructure.database.session import create_engine, create_session_factory
from presentation.telegram.handlers.start import (
    INVALID_INVITE_TEXT,
    REGISTRATION_SUCCESS_TEXT,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def synthetic_start_update(
    *,
    update_id: int,
    telegram_id: int,
    token: str,
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
                first_name="Functional",
                last_name="User",
                username=f"functional_{telegram_id}",
            ),
            text=f"/start {token}",
        ),
    )


async def test_synthetic_start_registration_flow(
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

    valid_telegram_id = 3_000_000 + uuid4().int % 1_000_000_000
    invalid_telegram_id = 4_000_000 + uuid4().int % 1_000_000_000
    try:
        await bootstrap_system_roles(container)
        raw_token = await create_development_invite(container)
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)

        await dispatcher.feed_update(
            bot,
            synthetic_start_update(
                update_id=1,
                telegram_id=valid_telegram_id,
                token=raw_token,
            ),
        )
        await dispatcher.feed_update(
            bot,
            synthetic_start_update(
                update_id=2,
                telegram_id=invalid_telegram_id,
                token="invalid-token",
            ),
        )

        assert [
            method.text for method in sent_methods if isinstance(method, SendMessage)
        ] == [REGISTRATION_SUCCESS_TEXT, INVALID_INVITE_TEXT]

        engine = create_engine(integration_settings.database_url)
        session_factory = create_session_factory(engine)
        try:
            async with session_factory() as session:
                user = await session.scalar(
                    select(UserModel).where(
                        UserModel.telegram_id == valid_telegram_id
                    )
                )
                invalid_user = await session.scalar(
                    select(UserModel).where(
                        UserModel.telegram_id == invalid_telegram_id
                    )
                )
                assert user is not None
                role_code = await session.scalar(
                    select(RoleModel.code)
                    .join(
                        UserRoleModel,
                        UserRoleModel.role_id == RoleModel.id,
                    )
                    .where(UserRoleModel.user_id == user.id)
                )
                audit = await session.scalar(
                    select(AuditLogModel).where(
                        AuditLogModel.entity_id == user.id,
                        AuditLogModel.action == "USER_REGISTERED",
                    )
                )
                athlete = await session.scalar(
                    select(AthleteModel).where(
                        AthleteModel.user_id == user.id
                    )
                )
            assert role_code == "ATHLETE"
            assert audit is not None
            assert athlete is not None
            assert athlete.user_id == user.id
            assert athlete.athlete_public_id.version == 4
            assert athlete.first_name == "Functional"
            assert athlete.last_name == "User"
            assert athlete.phone is None
            assert athlete.is_active
            assert invalid_user is None
        finally:
            await engine.dispose()
    finally:
        await container.close()


async def test_bot_process_starts_without_telegram_network_call(
    integration_settings: Settings,
    monkeypatch: Any,
) -> None:
    polling_calls: list[tuple[Bot, ...]] = []

    async def fake_start_polling(
        dispatcher: Any,
        *bots: Bot,
        **kwargs: Any,
    ) -> None:
        del dispatcher, kwargs
        polling_calls.append(bots)

    monkeypatch.setattr(
        "entrypoints.bot.Dispatcher.start_polling",
        fake_start_polling,
    )

    await run_bot(integration_settings)

    assert len(polling_calls) == 1
    assert len(polling_calls[0]) == 1
