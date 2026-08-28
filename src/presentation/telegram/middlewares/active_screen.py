from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from presentation.telegram.ui_context import get_active_ui_message

logger = structlog.get_logger()

STALE_SCREEN_TEXT = (
    "Этот экран уже неактивен. Используйте последнее сообщение."
)
_EXPIRED_CALLBACK_QUERY_ERROR_MESSAGE = (
    "Bad Request: query is too old and response timeout expired or query ID "
    "is invalid"
)


def _is_expired_callback_query_error(error: TelegramBadRequest) -> bool:
    return (
        error.message.strip().casefold()
        == _EXPIRED_CALLBACK_QUERY_ERROR_MESSAGE.casefold()
    )


async def _acknowledge_callback(
    callback: CallbackQuery,
    *,
    text: str | None = None,
) -> bool:
    try:
        if text is None:
            await callback.answer()
        else:
            await callback.answer(text)
    except TelegramBadRequest as error:
        if not _is_expired_callback_query_error(error):
            raise
        logger.info(
            "telegram_callback_acknowledgement_expired",
            message_id=getattr(callback.message, "message_id", None),
            stale=text is not None,
        )
        return False
    return True


class ActiveScreenCallbackMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[
            [TelegramObject, dict[str, Any]],
            Awaitable[Any],
        ],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        state = data.get("state")
        active = (
            await get_active_ui_message(state)
            if isinstance(state, FSMContext)
            else None
        )
        message_id = getattr(event.message, "message_id", None)
        if active is None or message_id != active.message_id:
            await _acknowledge_callback(event, text=STALE_SCREEN_TEXT)
            return None

        if not await _acknowledge_callback(event):
            return None
        return await handler(event, data)
