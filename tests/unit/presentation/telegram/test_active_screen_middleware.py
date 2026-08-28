from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, User

from presentation.telegram.middlewares import active_screen
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
EXPIRED_CALLBACK_QUERY_ERROR = (
    "Bad Request: query is too old and response timeout expired or query ID "
    "is invalid"
)


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


def telegram_bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(
        method=AnswerCallbackQuery(callback_query_id="callback"),
        message=message,
    )


async def test_active_callback_is_answered_once_before_handler() -> None:
    state = make_state()
    await set_active_screen(state)
    callback, answer = make_callback(ACTIVE_MESSAGE_ID)
    events: list[str] = []

    async def answer_callback() -> None:
        events.append("ack")

    async def handle_callback(
        event: CallbackQuery,
        data: dict[str, object],
    ) -> str:
        del event, data
        events.append("handler")
        return "handled"

    answer.side_effect = answer_callback
    handler = AsyncMock(side_effect=handle_callback)

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result == "handled"
    assert events == ["ack", "handler"]
    handler.assert_awaited_once_with(callback, {"state": state})
    answer.assert_awaited_once_with()


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


async def test_missing_active_screen_is_answered_as_stale_and_stops() -> None:
    state = make_state()
    callback, answer = make_callback(ACTIVE_MESSAGE_ID)
    handler = AsyncMock()

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result is None
    answer.assert_awaited_once_with(STALE_SCREEN_TEXT)
    handler.assert_not_awaited()


async def test_expired_active_callback_stops_without_state_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = make_state()
    await state.set_state("form:waiting_for_input")
    await state.update_data(flow_context={"first_name": "Иван"})
    await set_active_screen(state)
    state_before = await state.get_state()
    data_before = await state.get_data()
    callback, answer = make_callback(ACTIVE_MESSAGE_ID)
    answer.side_effect = telegram_bad_request(EXPIRED_CALLBACK_QUERY_ERROR)
    handler = AsyncMock()
    log = Mock()
    monkeypatch.setattr(active_screen, "logger", log)

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result is None
    answer.assert_awaited_once_with()
    handler.assert_not_awaited()
    assert await state.get_state() == state_before
    assert await state.get_data() == data_before
    log.info.assert_called_once_with(
        "telegram_callback_acknowledgement_expired",
        message_id=ACTIVE_MESSAGE_ID,
        stale=False,
    )


async def test_expired_stale_callback_stops_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = make_state()
    await set_active_screen(state)
    callback, answer = make_callback(ACTIVE_MESSAGE_ID - 1)
    answer.side_effect = telegram_bad_request(EXPIRED_CALLBACK_QUERY_ERROR)
    handler = AsyncMock()
    log = Mock()
    monkeypatch.setattr(active_screen, "logger", log)

    result = await ActiveScreenCallbackMiddleware()(
        handler,
        callback,
        {"state": state},
    )

    assert result is None
    answer.assert_awaited_once_with(STALE_SCREEN_TEXT)
    handler.assert_not_awaited()
    log.info.assert_called_once_with(
        "telegram_callback_acknowledgement_expired",
        message_id=ACTIVE_MESSAGE_ID - 1,
        stale=True,
    )


async def test_unexpected_telegram_bad_request_is_reraised() -> None:
    state = make_state()
    await set_active_screen(state)
    callback, answer = make_callback(ACTIVE_MESSAGE_ID)
    error = telegram_bad_request("Bad Request: message is not modified")
    answer.side_effect = error
    handler = AsyncMock()

    with pytest.raises(TelegramBadRequest) as exc_info:
        await ActiveScreenCallbackMiddleware()(
            handler,
            callback,
            {"state": state},
        )

    assert exc_info.value is error
    answer.assert_awaited_once_with()
    handler.assert_not_awaited()
