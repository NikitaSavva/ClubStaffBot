from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
    GetUserMenuContextQuery,
)
from application.identity.errors import UserHasNoRolesError, UserNotFoundError
from presentation.telegram.keyboards import build_menu_keyboard

MENU_TEXT = "Выберите доступный раздел."
USER_NOT_REGISTERED_TEXT = (
    "Сначала зарегистрируйтесь по ссылке-приглашению на ресепшене."
)
MENU_UNAVAILABLE_TEXT = "Для вашей учетной записи пока нет доступного меню."


@inject
async def handle_menu(
    message: Message,
    interactor: FromDishka[GetUserMenuContextInteractor],
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        await message.answer(USER_NOT_REGISTERED_TEXT)
        return

    try:
        context = await interactor(
            GetUserMenuContextQuery(telegram_id=telegram_user.id)
        )
    except UserNotFoundError:
        await message.answer(USER_NOT_REGISTERED_TEXT)
    except UserHasNoRolesError:
        await message.answer(MENU_UNAVAILABLE_TEXT)
    else:
        await message.answer(
            MENU_TEXT,
            reply_markup=build_menu_keyboard(context),
        )


def create_menu_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_menu, Command("menu"))
    return router
