import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from application.notification_delivery import (
    PermanentNotificationSenderError,
    RetryableNotificationSenderError,
)

TELEGRAM_REQUEST_TIMEOUT_SECONDS = 20
logger = structlog.get_logger()


class AiogramProactiveNotificationSender:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(
        self,
        *,
        telegram_id: int,
        text: str,
        notification_type: str,
    ) -> None:
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=text,
                request_timeout=TELEGRAM_REQUEST_TIMEOUT_SECONDS,
            )
        except TelegramRetryAfter as error:
            logger.warning(
                "notification_telegram_retry_after",
                notification_type=notification_type,
                telegram_id=telegram_id,
                retry_after_seconds=error.retry_after,
                error_type=type(error).__name__,
            )
            raise RetryableNotificationSenderError(
                retry_after_seconds=error.retry_after
            ) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            logger.warning(
                "notification_telegram_retryable_error",
                notification_type=notification_type,
                telegram_id=telegram_id,
                error_type=type(error).__name__,
            )
            raise RetryableNotificationSenderError from error
        except TelegramAPIError as error:
            logger.error(
                "notification_telegram_permanent_error",
                notification_type=notification_type,
                telegram_id=telegram_id,
                error_type=type(error).__name__,
            )
            raise PermanentNotificationSenderError from error
