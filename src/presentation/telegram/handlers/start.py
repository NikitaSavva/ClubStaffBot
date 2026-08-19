from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    RegisterBotUserCommand,
    RegisterBotUserInteractor,
)
from application.identity.errors import (
    InvalidBotInviteError,
    RequiredSystemRoleMissingError,
    UserAlreadyRegisteredError,
)

INVALID_INVITE_TEXT = "Ссылка-приглашение недействительна или больше не активна."
ALREADY_REGISTERED_TEXT = "Вы уже зарегистрированы."
REGISTRATION_UNAVAILABLE_TEXT = (
    "Сейчас не удалось завершить регистрацию. Обратитесь к администратору."
)
REGISTRATION_SUCCESS_TEXT = "Регистрация завершена."


@inject
async def handle_start(
    message: Message,
    command: CommandObject,
    interactor: FromDishka[RegisterBotUserInteractor],
) -> None:
    telegram_user = message.from_user
    invite_token = command.args
    if telegram_user is None or not invite_token:
        await message.answer(INVALID_INVITE_TEXT)
        return

    try:
        await interactor(
            RegisterBotUserCommand(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                invite_token=invite_token,
            )
        )
    except InvalidBotInviteError:
        await message.answer(INVALID_INVITE_TEXT)
    except UserAlreadyRegisteredError:
        await message.answer(ALREADY_REGISTERED_TEXT)
    except RequiredSystemRoleMissingError:
        await message.answer(REGISTRATION_UNAVAILABLE_TEXT)
    else:
        await message.answer(REGISTRATION_SUCCESS_TEXT)


def create_start_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_start, CommandStart())
    return router
