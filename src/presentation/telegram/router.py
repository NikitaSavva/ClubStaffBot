from aiogram import Router

from presentation.telegram.handlers.menu import create_menu_router
from presentation.telegram.handlers.start import create_start_router


def create_telegram_router() -> Router:
    router = Router(name=__name__)
    router.include_router(create_start_router())
    router.include_router(create_menu_router())
    return router
