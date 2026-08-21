from aiogram import Router

from presentation.telegram.handlers.account_link import (
    create_account_link_router,
)
from presentation.telegram.handlers.athlete_creation import (
    create_athlete_creation_router,
)
from presentation.telegram.handlers.menu import create_menu_router
from presentation.telegram.handlers.start import create_start_router


def create_telegram_router() -> Router:
    router = Router(name=__name__)
    router.include_router(create_start_router())
    router.include_router(create_menu_router())
    router.include_router(create_account_link_router())
    router.include_router(create_athlete_creation_router())
    return router
