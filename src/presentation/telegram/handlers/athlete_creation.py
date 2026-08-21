from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import (
    CreateManualAthleteCommand,
    CreateManualAthleteInteractor,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
from domain.identity import AthleteFirstNameRequiredError
from presentation.telegram.states import CreateAthleteStates

CREATE_ATHLETE_ACTION = "administrator.create_athlete"
ENTER_FIRST_NAME_TEXT = (
    "Введите имя спортсмена без фамилии. Для отмены отправьте /cancel."
)
INVALID_FIRST_NAME_TEXT = "Имя не может быть пустым. Введите имя еще раз."
CREATE_ATHLETE_CANCELLED_TEXT = "Создание спортсмена отменено."
CREATE_ATHLETE_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору."
)
CREATE_ATHLETE_SUCCESS_TEXT = "Спортсмен {first_name} создан."


async def handle_begin_create_athlete(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await state.clear()
    await state.set_state(CreateAthleteStates.waiting_for_first_name)
    await message.answer(ENTER_FIRST_NAME_TEXT)


async def handle_cancel_create_athlete(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(CREATE_ATHLETE_CANCELLED_TEXT)


@inject
async def handle_create_athlete_first_name(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[CreateManualAthleteInteractor],
) -> None:
    telegram_user = message.from_user
    first_name = message.text.strip() if message.text is not None else ""
    if telegram_user is None or not first_name:
        await message.answer(INVALID_FIRST_NAME_TEXT)
        return

    try:
        result = await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=telegram_user.id,
                first_name=first_name,
            )
        )
    except AthleteFirstNameRequiredError:
        await message.answer(INVALID_FIRST_NAME_TEXT)
        return
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await state.clear()
        await message.answer(CREATE_ATHLETE_PERMISSION_DENIED_TEXT)
        return

    await state.clear()
    await message.answer(
        CREATE_ATHLETE_SUCCESS_TEXT.format(first_name=result.first_name)
    )


def create_athlete_creation_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_create_athlete,
        F.data == CREATE_ATHLETE_ACTION,
    )
    router.message.register(
        handle_cancel_create_athlete,
        Command("cancel"),
        CreateAthleteStates.waiting_for_first_name,
    )
    router.message.register(
        handle_create_athlete_first_name,
        CreateAthleteStates.waiting_for_first_name,
    )
    return router
