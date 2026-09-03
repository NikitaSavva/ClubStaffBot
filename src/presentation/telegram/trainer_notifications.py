from aiogram import Bot

from application.trainer_notifications import (
    TrainerNotificationMessage,
    TrainerNotifier,
)
from presentation.telegram.proactive_notifications import (
    AiogramProactiveNotificationSender,
)

NOTIFICATION_TYPE = "TRAINER_SESSION_MINUS_5"


class AiogramTrainerNotifier(TrainerNotifier):
    def __init__(self, bot: Bot) -> None:
        self._sender = AiogramProactiveNotificationSender(bot)

    async def send(
        self,
        *,
        telegram_id: int,
        message: TrainerNotificationMessage,
    ) -> None:
        await self._sender.send_text(
            telegram_id=telegram_id,
            text=format_trainer_notification(message),
            notification_type=NOTIFICATION_TYPE,
        )


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
