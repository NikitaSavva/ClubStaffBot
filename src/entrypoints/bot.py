import asyncio

from aiogram import Bot, Dispatcher
from dishka import AsyncContainer
from dishka.integrations.aiogram import setup_dishka

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.startup import bootstrap_system_roles
from presentation.telegram import create_telegram_router


def create_dispatcher(container: AsyncContainer) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(create_telegram_router())
    setup_dishka(container=container, router=dispatcher)
    return dispatcher


async def run_bot(settings: Settings | None = None) -> None:
    container = create_container(settings)
    dispatcher = create_dispatcher(container)

    try:
        await bootstrap_system_roles(container)
        bot = await container.get(Bot)
        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
