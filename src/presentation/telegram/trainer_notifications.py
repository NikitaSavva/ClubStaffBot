import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from application.trainer_notifications import (
    PermanentTrainerNotifierError,
    RetryableTrainerNotifierError,
    TrainerNotificationMessage,
    TrainerNotifier,
)

TELEGRAM_REQUEST_TIMEOUT_SECONDS = 20
logger = structlog.get_logger()


class AiogramTrainerNotifier(TrainerNotifier):
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None:
        try:
            await self._bot.send_message(
                chat_id=telegram_id,
                text=format_trainer_notification(message),
                request_timeout=TELEGRAM_REQUEST_TIMEOUT_SECONDS,
            )
        except TelegramRetryAfter as error:
            logger.warning(
                "trainer_notification_telegram_retry_after",
                telegram_id=telegram_id,
                retry_after_seconds=error.retry_after,
                error_type=type(error).__name__,
            )
            raise RetryableTrainerNotifierError(
                retry_after_seconds=error.retry_after
            ) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            logger.warning(
                "trainer_notification_telegram_retryable_error",
                telegram_id=telegram_id,
                error_type=type(error).__name__,
            )
            raise RetryableTrainerNotifierError from error
        except TelegramAPIError as error:
            logger.error(
                "trainer_notification_telegram_permanent_error",
                telegram_id=telegram_id,
                error_type=type(error).__name__,
            )
            raise PermanentTrainerNotifierError from error


def format_trainer_notification(message: TrainerNotificationMessage) -> str:
    start = message.starts_at.strftime("%H:%M")
    end = message.ends_at.strftime("%H:%M")
    return (
        "Через 5 минут тренировка\n\n"
        f"{message.sport_direction_name} · {message.group_name} · "
        f"{start}–{end}\n\n"
        f"Ожидалось: {message.expected_count} "
        f"{_people_word(message.expected_count)}\n"
        f"Отметились: {message.confirmed_count} "
        f"{_people_word(message.confirmed_count)}"
    )


def _people_word(count: int) -> str:
    last_two = count % 100
    if 11 <= last_two <= 14:
        return "человек"
    last = count % 10
    if last == 1:
        return "человек"
    if 2 <= last <= 4:
        return "человека"
    return "человек"
