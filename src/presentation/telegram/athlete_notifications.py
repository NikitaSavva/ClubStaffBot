from aiogram import Bot

from application.athlete_notifications import (
    AthleteNotificationMessage,
    AthleteNotifier,
)
from presentation.telegram.proactive_notifications import (
    AiogramProactiveNotificationSender,
)

NOTIFICATION_TYPE = "ATHLETE_SESSION_MINUS_2H"


class AiogramAthleteNotifier(AthleteNotifier):
    def __init__(self, bot: Bot) -> None:
        self._sender = AiogramProactiveNotificationSender(bot)

    async def send(
        self,
        *,
        telegram_id: int,
        message: AthleteNotificationMessage,
    ) -> None:
        await self._sender.send_text(
            telegram_id=telegram_id,
            text=format_athlete_notification(message),
            notification_type=NOTIFICATION_TYPE,
        )


def format_athlete_notification(message: AthleteNotificationMessage) -> str:
    start = message.starts_at.strftime("%H:%M")
    end = message.ends_at.strftime("%H:%M")
    return (
        "Через 2 часа тренировка\n\n"
        f"{message.sport_direction_name} · {message.group_name} · "
        f"{start}–{end}"
    )
