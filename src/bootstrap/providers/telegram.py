from collections.abc import AsyncIterator

from aiogram import Bot
from dishka import Provider, Scope, provide

from application.trainer_notifications import TrainerNotifier
from bootstrap.config import Settings
from presentation.telegram.screen import BannerFileIds, TelegramScreenRenderer
from presentation.telegram.trainer_notifications import AiogramTrainerNotifier


class TelegramProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_bot(self, settings: Settings) -> AsyncIterator[Bot]:
        bot = Bot(token=settings.telegram_bot_token.get_secret_value())
        try:
            yield bot
        finally:
            await bot.session.close()

    @provide(scope=Scope.APP)
    def provide_trainer_notifier(self, bot: Bot) -> TrainerNotifier:
        return AiogramTrainerNotifier(bot)

    @provide(scope=Scope.APP)
    def provide_screen_renderer(
        self,
        bot: Bot,
        settings: Settings,
    ) -> TelegramScreenRenderer:
        return TelegramScreenRenderer(
            bot=bot,
            banner_file_ids=BannerFileIds(
                role_selector=settings.role_selector_banner_file_id,
                owner_panel=settings.owner_panel_banner_file_id,
                admin_panel=settings.admin_panel_banner_file_id,
                trainer_panel=settings.trainer_panel_banner_file_id,
                athlete_panel=settings.athlete_panel_banner_file_id,
            ),
        )
