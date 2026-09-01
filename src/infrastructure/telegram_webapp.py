from datetime import timedelta

from aiogram.utils.web_app import safe_parse_webapp_init_data

from application.common import Clock
from application.scanner import (
    TelegramWebAppInitDataExpiredError,
    TelegramWebAppInitDataInvalidError,
    TrustedTelegramWebAppUser,
)


class AiogramTelegramWebAppInitDataVerifier:
    def __init__(
        self,
        *,
        bot_token: str,
        max_age_seconds: int,
        clock: Clock,
    ) -> None:
        self._bot_token = bot_token
        self._max_age = timedelta(seconds=max_age_seconds)
        self._clock = clock

    def verify(self, raw_init_data: str) -> TrustedTelegramWebAppUser:
        if not raw_init_data:
            raise TelegramWebAppInitDataInvalidError
        try:
            init_data = safe_parse_webapp_init_data(
                token=self._bot_token,
                init_data=raw_init_data,
            )
        except (TypeError, ValueError) as error:
            raise TelegramWebAppInitDataInvalidError from error

        if init_data.user is None or init_data.user.id <= 0:
            raise TelegramWebAppInitDataInvalidError
        if init_data.auth_date.tzinfo is None:
            raise TelegramWebAppInitDataInvalidError

        now = self._clock.now()
        if now.tzinfo is None:
            raise RuntimeError("Clock must return a timezone-aware datetime")
        if init_data.auth_date > now:
            raise TelegramWebAppInitDataInvalidError
        if now - init_data.auth_date > self._max_age:
            raise TelegramWebAppInitDataExpiredError

        return TrustedTelegramWebAppUser(
            telegram_user_id=init_data.user.id
        )
