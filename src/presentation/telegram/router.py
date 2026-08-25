from aiogram import Router

from presentation.telegram.handlers.account_link import (
    create_account_link_router,
)
from presentation.telegram.handlers.athlete_creation import (
    create_athlete_creation_router,
)
from presentation.telegram.handlers.menu import create_menu_router
from presentation.telegram.handlers.role_management import (
    create_role_management_router,
)
from presentation.telegram.handlers.start import create_start_router
from presentation.telegram.middlewares import ActiveScreenCallbackMiddleware


def create_telegram_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.outer_middleware(ActiveScreenCallbackMiddleware())
    router.include_router(create_start_router())
    router.include_router(create_menu_router())
    router.include_router(create_account_link_router())
    router.include_router(create_athlete_creation_router())
    router.include_router(create_role_management_router())
    return router
