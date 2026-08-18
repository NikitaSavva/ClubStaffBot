import asyncio

from aiogram import Bot, Dispatcher
from dishka.integrations.aiogram import setup_dishka

from bootstrap.config import Settings
from bootstrap.container import create_container


async def run_bot(settings: Settings | None = None) -> None:
    container = create_container(settings)
    dispatcher = Dispatcher()
    setup_dishka(container=container, router=dispatcher)

    try:
        bot = await container.get(Bot)
        await dispatcher.start_polling(bot, close_bot_session=False)
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
