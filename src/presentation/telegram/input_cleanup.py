import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

logger = structlog.get_logger()


async def cleanup_accepted_user_input(message: Message) -> None:
    """Best-effort cleanup for validated temporary form input."""
    try:
        await message.delete()
    except TelegramAPIError as error:
        logger.warning(
            "telegram_temporary_user_input_cleanup_failed",
            chat_id=message.chat.id,
            message_id=message.message_id,
            error_type=type(error).__name__,
        )
