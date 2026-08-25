from datetime import UTC, datetime
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from presentation.telegram.middlewares.active_screen import (
    STALE_SCREEN_TEXT,
    ActiveScreenCallbackMiddleware,
)
from presentation.telegram.ui_context import (
    ActiveUiMessage,
    UiMessageKind,
    set_active_ui_message,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
CHAT_ID = 123456
ACTIVE_MESSAGE_ID = 200


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=CHAT_ID, user_id=CHAT_ID),
    )


def make_callback(message_id: int) -> tuple[CallbackQuery, AsyncMock]:
    callback = CallbackQuery(
        id=f"callback-{message_id}",
        from_user=User(id=CHAT_ID, is_bot=False, first_name="User"),
        chat_instance=f"chat-{CHAT_ID}",
        data="action",
        message=Message(
            message_id=message_id,
            date=NOW,
            chat=Chat(id=CHAT_ID, type="private"),
        ),
    )
    answer = AsyncMock()
    object.__setattr__(callback, "answer", answer)
    return callback, answer


async def set_active_screen(state: FSMContext) -> None:
    await set_active_ui_message(
        state,
        ActiveUiMessage(
            chat_id=CHAT_ID,
            message_id=ACTIVE_MESSAGE_ID,
            kind=UiMessageKind.TEXT,
            media_key=None,
            content_fingerprint="content",
            keyboard_fingerprint="keyboard",
        ),
    )


async def test_active_callback_reaches_handler_without_guard_answer() -> None:
    state = make_state()
    await set_active_screen(state)
    callback, answer = make_callback(ACTIVE_MESSAGE_ID)
    handler = AsyncMock(return_value="handled")

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result == "handled"
    handler.assert_awaited_once_with(callback, {"state": state})
    answer.assert_not_awaited()


async def test_stale_callback_is_answered_once_and_stops_before_handler() -> None:
    state = make_state()
    await state.set_state("form:waiting_for_input")
    await state.update_data(flow_context={"first_name": "Иван"})
    await set_active_screen(state)
    state_before = await state.get_state()
    data_before = await state.get_data()
    callback, answer = make_callback(ACTIVE_MESSAGE_ID - 1)
    handler = AsyncMock()

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result is None
    answer.assert_awaited_once_with(STALE_SCREEN_TEXT)
    handler.assert_not_awaited()
    assert await state.get_state() == state_before
    assert await state.get_data() == data_before
