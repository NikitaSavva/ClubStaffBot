from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText
from aiogram.types import Chat, Message

from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.screen import (
    BannerContext,
    BannerFileIds,
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.ui_context import (
    UiMessageKind,
    get_active_ui_message,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
CHAT_ID = 123456


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=CHAT_ID, user_id=CHAT_ID),
    )


def bot_message(message_id: int) -> Message:
    return Message(
        message_id=message_id,
        date=NOW,
        chat=Chat(id=CHAT_ID, type="private"),
    )


def make_renderer() -> tuple[TelegramScreenRenderer, AsyncMock]:
    bot_mock = AsyncMock(spec=Bot)
    renderer = TelegramScreenRenderer(
        bot=cast(Bot, bot_mock),
        banner_file_ids=BannerFileIds(
            role_selector="selector-file-id",
            admin_panel="admin-file-id",
            trainer_panel="trainer-file-id",
            athlete_panel="athlete-file-id",
        ),
    )
    return renderer, bot_mock


async def test_edit_mode_edits_active_screen() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_message.return_value = bot_message(5)

    previous = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Initial"),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Updated"),
        mode=RenderMode.EDIT,
    )

    assert bot.send_message.await_count == 1
    bot.edit_message_text.assert_awaited_once()
    assert active.message_id == previous.message_id
    assert await get_active_ui_message(state) == active


async def test_new_mode_keeps_old_keyboard_and_sends_new_active_screen() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_photo.return_value = bot_message(6)
    bot.send_message.return_value = bot_message(7)
    keyboard = build_inline_keyboard(
        (build_callback_button(text="Start", callback_data="start"),)
    )

    previous = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Admin panel",
            reply_markup=keyboard,
            banner=BannerContext.ADMIN_PANEL,
        ),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Input prompt",
            reply_markup=keyboard,
        ),
        mode=RenderMode.NEW,
    )

    assert bot.send_photo.await_count == 1
    assert bot.send_message.await_count == 1
    bot.edit_message_reply_markup.assert_not_awaited()
    bot.edit_message_caption.assert_not_awaited()
    assert active.message_id == 7
    assert active.message_id != previous.message_id
    assert await get_active_ui_message(state) == active


async def test_text_to_media_sends_replacement_screen() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_message.return_value = bot_message(10)
    bot.send_photo.return_value = bot_message(11)
    keyboard = build_inline_keyboard(
        (build_callback_button(text="Continue", callback_data="continue"),)
    )

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Text screen", reply_markup=keyboard),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Media screen",
            banner=BannerContext.ADMIN_PANEL,
        ),
    )

    assert bot.send_message.await_count == 1
    assert bot.send_photo.await_count == 1
    bot.edit_message_reply_markup.assert_not_awaited()
    bot.edit_message_media.assert_not_awaited()
    assert active.message_id == 11
    assert active.kind is UiMessageKind.MEDIA


async def test_media_to_media_edits_caption_then_media() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_photo.return_value = bot_message(20)

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Admin panel",
            banner=BannerContext.ADMIN_PANEL,
        ),
    )
    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Users",
            banner=BannerContext.ADMIN_PANEL,
        ),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Trainer panel",
            banner=BannerContext.TRAINER_PANEL,
        ),
    )

    bot.edit_message_caption.assert_awaited_once()
    bot.edit_message_media.assert_awaited_once()
    assert active.message_id == 20
    assert active.media_key == "banner:trainer_panel"


async def test_media_to_text_sends_replacement_screen() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_photo.return_value = bot_message(30)
    bot.send_message.return_value = bot_message(31)
    keyboard = build_inline_keyboard(
        (build_callback_button(text="Continue", callback_data="continue"),)
    )

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Media screen",
            reply_markup=keyboard,
            banner=BannerContext.ADMIN_PANEL,
        ),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Text screen"),
    )

    assert bot.send_photo.await_count == 1
    assert bot.send_message.await_count == 1
    bot.edit_message_reply_markup.assert_not_awaited()
    assert active.message_id == 31
    assert active.kind is UiMessageKind.TEXT


async def test_edit_failure_sends_new_active_screen() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_message.side_effect = [bot_message(40), bot_message(41)]
    keyboard = build_inline_keyboard(
        (build_callback_button(text="Continue", callback_data="continue"),)
    )
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(
            chat_id=CHAT_ID,
            message_id=40,
            text="Updated",
        ),
        message="message to edit not found",
    )

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Initial", reply_markup=keyboard),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Updated"),
    )

    bot.edit_message_text.assert_awaited_once()
    bot.edit_message_reply_markup.assert_not_awaited()
    assert bot.send_message.await_count == 2
    assert active.message_id == 41
    assert await get_active_ui_message(state) == active


async def test_new_send_failure_keeps_previous_active_context() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    keyboard = build_inline_keyboard(
        (build_callback_button(text="Continue", callback_data="continue"),)
    )
    bot.send_message.side_effect = [bot_message(45), RuntimeError("send failed")]

    previous = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Initial", reply_markup=keyboard),
    )

    with pytest.raises(RuntimeError, match="send failed"):
        await renderer.render(
            state=state,
            chat_id=CHAT_ID,
            screen=TelegramScreen(text="Replacement", reply_markup=keyboard),
            mode=RenderMode.NEW,
        )

    bot.edit_message_reply_markup.assert_not_awaited()
    assert await get_active_ui_message(state) == previous


async def test_message_not_modified_does_not_send_duplicate() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_message.return_value = bot_message(50)
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(
            chat_id=CHAT_ID,
            message_id=50,
            text="Updated",
        ),
        message="message is not modified",
    )

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Initial"),
    )
    active = await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(text="Updated"),
    )

    assert bot.send_message.await_count == 1
    assert active.message_id == 50


async def test_keyboard_only_change_uses_reply_markup_edit() -> None:
    renderer, bot = make_renderer()
    state = make_state()
    bot.send_message.return_value = bot_message(60)
    first_keyboard = build_inline_keyboard(
        (build_callback_button(text="A", callback_data="a"),)
    )
    second_keyboard = build_inline_keyboard(
        (build_callback_button(text="B", callback_data="b"),)
    )

    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Same content",
            reply_markup=first_keyboard,
        ),
    )
    await renderer.render(
        state=state,
        chat_id=CHAT_ID,
        screen=TelegramScreen(
            text="Same content",
            reply_markup=second_keyboard,
        ),
    )

    bot.edit_message_reply_markup.assert_awaited_once()
    bot.edit_message_text.assert_not_awaited()
