from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    LinkAthleteAccountResult,
    RegisterBotUserCommand,
    RegisterBotUserInteractor,
)
from application.identity.errors import (
    AthleteAlreadyLinkedError,
    AthleteNotFoundError,
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
ACCOUNT_LINK_SUCCESS_TEXT = "Telegram-аккаунт связан со спортсменом."
ATHLETE_ALREADY_LINKED_TEXT = "Спортсмен уже связан с Telegram-аккаунтом."


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
        result = await interactor(
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
    except AthleteAlreadyLinkedError:
        await message.answer(ATHLETE_ALREADY_LINKED_TEXT)
    except AthleteNotFoundError:
        await message.answer(INVALID_INVITE_TEXT)
    else:
        success_text = (
            ACCOUNT_LINK_SUCCESS_TEXT
            if isinstance(result, LinkAthleteAccountResult)
            else REGISTRATION_SUCCESS_TEXT
        )
        await message.answer(success_text)


def create_start_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_start, CommandStart())
    return router
