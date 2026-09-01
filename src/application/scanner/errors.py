from application.errors import ApplicationError


class TelegramWebAppInitDataInvalidError(ApplicationError):
    """Telegram Mini App initData cannot establish a trusted identity."""


class TelegramWebAppInitDataExpiredError(ApplicationError):
    """Telegram Mini App initData is older than the allowed session age."""
