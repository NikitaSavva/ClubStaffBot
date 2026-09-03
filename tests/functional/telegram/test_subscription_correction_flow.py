from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from aiogram import Bot
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    SendPhoto,
    TelegramMethod,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from domain.identity import SystemRoleCode
from domain.subscriptions import SubscriptionStatus
from entrypoints.bot import create_dispatcher
from infrastructure.database.models import AuditLogModel, SubscriptionModel
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
)
from presentation.telegram.handlers.subscription_correction import (
    STALE_SUBSCRIPTION_TEXT,
    VIEW_SUBSCRIPTION_ACTION,
    SubscriptionCorrectionAction,
    SubscriptionCorrectionCallback,
)
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from tests.functional.telegram.fakes import telegram_method_result
from tests.functional.telegram.test_subscription_activation_flow import (
    FlowData,
    active_message_id,
    arrange_flow_data,
    callback_texts,
    callback_update,
    cleanup_flow_data,
    command_update,
    last_screen,
    sent_message_id,
)


@pytest.mark.parametrize(
    "administrative_role",
    [SystemRoleCode.ADMINISTRATOR, SystemRoleCode.OWNER],
)
async def test_view_and_correct_latest_subscription_flow(
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
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        data = await arrange_flow_data(
            session_factory,
            administrative_role=administrative_role,
        )
        original_expiration = datetime(2026, 10, 3, 12, tzinfo=UTC)
        async with session_factory.begin() as session:
            subscription = SubscriptionModel(
                athlete_id=data.athlete_id,
                group_id=data.group_id,
                plan_id=data.specific_plan_id,
                activated_by_user_id=data.actor_user_id,
                activated_at=datetime(2026, 8, 26, 12, tzinfo=UTC),
                starts_at=datetime(2026, 8, 26, 12, tzinfo=UTC),
                expires_at=original_expiration,
                activation_price=Decimal("6000"),
                remaining_visits=7,
                status=SubscriptionStatus.ACTIVE,
            )
            session.add(subscription)
            await session.flush()
            subscription_id = subscription.id

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=1, sender=data.actor, text="/menu"),
        )
        menu_method = next(
            method for method in methods if isinstance(method, SendPhoto)
        )
        menu_id = sent_message_id(methods, menu_method)
        assert VIEW_SUBSCRIPTION_ACTION in callback_texts(last_screen(methods))

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=2,
                sender=data.actor,
                data=VIEW_SUBSCRIPTION_ACTION,
                message_id=menu_id,
            ),
        )
        assert last_screen(methods).text.startswith("Посмотреть абонемент")
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=3,
                sender=data.actor,
                data=AthleteSelectorCallback(
                    purpose=AthleteSelectionPurpose.SUBSCRIPTION_VIEW,
                    action=AthleteSelectorAction.SELECT,
                    value=str(data.athlete_id),
                ).pack(),
                message_id=await active_message_id(dispatcher, bot, data.actor),
            ),
        )
        card = last_screen(methods)
        assert card.text.startswith("Абонемент спортсмена")
        assert "Статус:\nАктивен" in card.text
        assert "Осталось посещений:\n7" in card.text

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=4,
            action=SubscriptionCorrectionAction.BEGIN,
        )
        assert last_screen(methods).text.startswith("Корректировка абонемента")

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=5,
            action=SubscriptionCorrectionAction.EDIT_REMAINING,
        )
        remaining_input_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=6, sender=data.actor, text="4"),
        )
        assert any(
            isinstance(method, DeleteMessage)
            for method in methods[remaining_input_offset:]
        )
        assert "7 → 4" in last_screen(methods).text

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=7,
            action=SubscriptionCorrectionAction.EDIT_EXPIRES_AT,
        )
        invalid_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=8, sender=data.actor, text="31.02.2026"),
        )
        assert "Некорректная дата" in last_screen(methods).text
        assert not any(
            isinstance(method, DeleteMessage) for method in methods[invalid_offset:]
        )

        expiration_input_offset = len(methods)
        await dispatcher.feed_update(
            bot,
            command_update(
                update_id=9,
                sender=data.actor,
                text="18.09.2026",
            ),
        )
        assert any(
            isinstance(method, DeleteMessage)
            for method in methods[expiration_input_offset:]
        )
        assert "03.10.2026 → 18.09.2026" in last_screen(methods).text

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=10,
            action=SubscriptionCorrectionAction.EDIT_STATUS,
        )
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=11,
            action=SubscriptionCorrectionAction.SET_STATUS,
            value=SubscriptionStatus.CANCELLED.value,
        )
        assert "Активен → Отменён" in last_screen(methods).text

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=12,
            action=SubscriptionCorrectionAction.REVIEW,
        )
        assert last_screen(methods).text.startswith(
            "Подтвердить корректировку абонемента?"
        )
        async with session_factory() as session:
            unchanged = await session.get(SubscriptionModel, subscription_id)
            audit_before = await session.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.entity_id == subscription_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
        assert unchanged is not None
        assert unchanged.remaining_visits == 7
        assert unchanged.expires_at == original_expiration
        assert unchanged.status is SubscriptionStatus.ACTIVE
        assert audit_before == 0

        confirmation_offset = len(methods)
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=13,
            action=SubscriptionCorrectionAction.CONFIRM,
        )

        success = last_screen(methods)
        assert success.text.startswith(
            "Абонемент скорректирован.\n\nАбонемент спортсмена"
        )
        assert "Осталось посещений:\n4" in success.text
        assert "Статус:\nОтменён" in success.text
        assert (
            sum(
                isinstance(method, AnswerCallbackQuery)
                for method in methods[confirmation_offset:]
            )
            == 1
        )
        async with session_factory() as session:
            updated = await session.get(SubscriptionModel, subscription_id)
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.entity_id == subscription_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
        expected_expiration = datetime(2026, 9, 18, 12, tzinfo=UTC)
        assert updated is not None
        assert updated.remaining_visits == 4
        assert updated.expires_at == expected_expiration
        assert updated.status is SubscriptionStatus.CANCELLED
        assert audit is not None
        assert audit.actor_user_id == data.actor_user_id
        assert audit.payload is not None
        assert audit.payload["changes"] == {
            "remaining_visits": {"before": 7, "after": 4},
            "expires_at": {
                "before": original_expiration.isoformat(),
                "after": expected_expiration.isoformat(),
            },
            "status": {"before": "ACTIVE", "after": "CANCELLED"},
        }
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def test_back_cancel_and_latest_race_are_controlled(
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
        session_factory = await container.get(async_sessionmaker[AsyncSession])
        data = await arrange_flow_data(
            session_factory,
            administrative_role=SystemRoleCode.ADMINISTRATOR,
        )
        async with session_factory.begin() as session:
            target = SubscriptionModel(
                athlete_id=data.athlete_id,
                group_id=data.group_id,
                plan_id=data.specific_plan_id,
                activated_by_user_id=data.actor_user_id,
                activated_at=datetime(2026, 8, 26, 12, tzinfo=UTC),
                starts_at=datetime(2026, 8, 26, 12, tzinfo=UTC),
                expires_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
                activation_price=Decimal("6000"),
                remaining_visits=7,
                status=SubscriptionStatus.ACTIVE,
            )
            session.add(target)
            await session.flush()
            target_id = target.id

        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container)
        await dispatcher.feed_update(
            bot,
            command_update(update_id=20, sender=data.actor, text="/menu"),
        )
        menu_method = next(
            method for method in methods if isinstance(method, SendPhoto)
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=21,
                sender=data.actor,
                data=VIEW_SUBSCRIPTION_ACTION,
                message_id=sent_message_id(methods, menu_method),
            ),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=22,
                sender=data.actor,
                data=AthleteSelectorCallback(
                    purpose=AthleteSelectionPurpose.SUBSCRIPTION_VIEW,
                    action=AthleteSelectorAction.SELECT,
                    value=str(data.athlete_id),
                ).pack(),
                message_id=await active_message_id(dispatcher, bot, data.actor),
            ),
        )
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=23,
            action=SubscriptionCorrectionAction.BEGIN,
        )
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=24,
            action=SubscriptionCorrectionAction.EDIT_REMAINING,
        )

        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=25,
                sender=data.actor,
                data=NavigationCallback(
                    action=NavigationAction.BACK,
                    target=NavigationTarget.SUBSCRIPTION_CORRECTION_DRAFT,
                ).pack(),
                message_id=await active_message_id(dispatcher, bot, data.actor),
            ),
        )
        assert last_screen(methods).text.startswith("Корректировка абонемента")

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=26,
            action=SubscriptionCorrectionAction.EDIT_REMAINING,
        )
        await dispatcher.feed_update(
            bot,
            command_update(update_id=27, sender=data.actor, text="4"),
        )
        await dispatcher.feed_update(
            bot,
            callback_update(
                update_id=28,
                sender=data.actor,
                data=NavigationCallback(
                    action=NavigationAction.CANCEL,
                    target=NavigationTarget.SUBSCRIPTION_VIEW_CARD,
                ).pack(),
                message_id=await active_message_id(dispatcher, bot, data.actor),
            ),
        )
        assert last_screen(methods).text.startswith("Абонемент спортсмена")
        async with session_factory() as session:
            unchanged_after_cancel = await session.get(SubscriptionModel, target_id)
        assert unchanged_after_cancel is not None
        assert unchanged_after_cancel.remaining_visits == 7

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=29,
            action=SubscriptionCorrectionAction.BEGIN,
        )
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=30,
            action=SubscriptionCorrectionAction.EDIT_REMAINING,
        )
        await dispatcher.feed_update(
            bot,
            command_update(update_id=31, sender=data.actor, text="4"),
        )
        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=32,
            action=SubscriptionCorrectionAction.REVIEW,
        )

        async with session_factory.begin() as session:
            newer = SubscriptionModel(
                athlete_id=data.athlete_id,
                group_id=data.group_id,
                plan_id=data.specific_plan_id,
                activated_by_user_id=data.actor_user_id,
                activated_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
                starts_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
                expires_at=datetime(2026, 11, 1, 12, tzinfo=UTC),
                activation_price=Decimal("6000"),
                remaining_visits=2,
                status=SubscriptionStatus.CANCELLED,
            )
            session.add(newer)
            await session.flush()

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=33,
            action=SubscriptionCorrectionAction.CONFIRM,
        )
        stale = last_screen(methods)
        assert stale.text == STALE_SUBSCRIPTION_TEXT
        assert "Открыть данные заново" in callback_texts(stale).values()
        async with session_factory() as session:
            unchanged_after_race = await session.get(SubscriptionModel, target_id)
            audit_count = await session.scalar(
                select(func.count(AuditLogModel.id)).where(
                    AuditLogModel.entity_id == target_id,
                    AuditLogModel.action == "SUBSCRIPTION_CORRECTED",
                )
            )
        assert unchanged_after_race is not None
        assert unchanged_after_race.remaining_visits == 7
        assert audit_count == 0

        await _click_correction_action(
            dispatcher=dispatcher,
            bot=bot,
            data=data,
            update_id=34,
            action=SubscriptionCorrectionAction.REOPEN,
        )
        reopened = last_screen(methods)
        assert "Осталось посещений:\n2" in reopened.text
        assert "Статус:\nОтменён" in reopened.text
    finally:
        if session_factory is not None and data is not None:
            await cleanup_flow_data(session_factory, data)
        await container.close()


async def _click_correction_action(
    *,
    dispatcher: Any,
    bot: Bot,
    data: FlowData,
    update_id: int,
    action: SubscriptionCorrectionAction,
    value: str = "0",
) -> None:
    await dispatcher.feed_update(
        bot,
        callback_update(
            update_id=update_id,
            sender=data.actor,
            data=SubscriptionCorrectionCallback(
                action=action,
                value=value,
            ).pack(),
            message_id=await active_message_id(
                dispatcher,
                bot,
                data.actor,
            ),
        ),
    )
