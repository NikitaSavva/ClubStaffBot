from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
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
from presentation.telegram.handlers.menu import show_home_screen
from presentation.telegram.screen import (
    BannerContext,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.ui_context import clear_flow_context

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
    state: FSMContext,
    interactor: FromDishka[RegisterBotUserInteractor],
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    invite_token = command.args
    if telegram_user is None:
        await clear_flow_context(state)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_status_screen(INVALID_INVITE_TEXT),
        )
        return
    if not invite_token:
        await clear_flow_context(state)
        await show_home_screen(
            chat_id=message.chat.id,
            telegram_id=telegram_user.id,
            state=state,
            interactor=menu_interactor,
            renderer=renderer,
        )
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
        response_text = INVALID_INVITE_TEXT
    except UserAlreadyRegisteredError:
        response_text = ALREADY_REGISTERED_TEXT
    except RequiredSystemRoleMissingError:
        response_text = REGISTRATION_UNAVAILABLE_TEXT
    except AthleteAlreadyLinkedError:
        response_text = ATHLETE_ALREADY_LINKED_TEXT
    except AthleteNotFoundError:
        response_text = INVALID_INVITE_TEXT
    else:
        success_text = (
            ACCOUNT_LINK_SUCCESS_TEXT
            if isinstance(result, LinkAthleteAccountResult)
            else REGISTRATION_SUCCESS_TEXT
        )
        await clear_flow_context(state)
        await show_home_screen(
            chat_id=message.chat.id,
            telegram_id=telegram_user.id,
            state=state,
            interactor=menu_interactor,
            renderer=renderer,
            notice=success_text,
        )
        return

    await clear_flow_context(state)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_status_screen(response_text),
    )


def create_start_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_start, CommandStart())
    return router


def _status_screen(text: str) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        banner=BannerContext.ROLE_SELECTOR,
    )
