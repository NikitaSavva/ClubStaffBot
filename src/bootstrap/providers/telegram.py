from collections.abc import AsyncIterator

from aiogram import Bot
from dishka import Provider, Scope, provide

from bootstrap.config import Settings


class TelegramProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_bot(self, settings: Settings) -> AsyncIterator[Bot]:
        bot = Bot(token=settings.telegram_bot_token.get_secret_value())
        try:
            yield bot
        finally:
            await bot.session.close()
