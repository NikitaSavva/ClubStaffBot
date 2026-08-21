from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
    GetUserMenuContextQuery,
)
from application.identity.errors import UserHasNoRolesError, UserNotFoundError
from presentation.telegram.keyboards import build_menu_keyboard
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)

MENU_TEXT = "Выберите доступный раздел."
USER_NOT_REGISTERED_TEXT = (
    "Сначала зарегистрируйтесь по ссылке-приглашению на ресепшене."
)
MENU_UNAVAILABLE_TEXT = "Для вашей учетной записи пока нет доступного меню."


@inject
async def handle_menu(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        await message.answer(USER_NOT_REGISTERED_TEXT)
        return

    await state.clear()
    await show_root_menu(
        message=message,
        telegram_id=telegram_user.id,
        interactor=interactor,
    )


async def show_root_menu(
    *,
    message: Message,
    telegram_id: int,
    interactor: GetUserMenuContextInteractor,
) -> None:
    try:
        context = await interactor(
            GetUserMenuContextQuery(telegram_id=telegram_id)
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


@inject
async def handle_back_to_root_menu(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await state.clear()
    await show_root_menu(
        message=message,
        telegram_id=callback.from_user.id,
        interactor=interactor,
    )


def create_menu_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_menu, Command("menu"))
    router.callback_query.register(
        handle_back_to_root_menu,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.MENU)
        ),
    )
    return router
