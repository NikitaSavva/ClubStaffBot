from aiogram import Bot, F, Router
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    CreateAthleteAccountLinkInviteCommand,
    CreateAthleteAccountLinkInviteInteractor,
    ListUnlinkedAthletesInteractor,
    ListUnlinkedAthletesQuery,
    UnlinkedAthlete,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteAlreadyLinkedError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
    build_back_button,
    build_menu_button,
    build_single_button_keyboard,
)
from presentation.telegram.qr import build_bot_start_deep_link, generate_qr_png

LINK_ACCOUNT_ACTION = "administrator.link_athlete_account"
SELECT_ATHLETE_PREFIX = "athlete_link.select:"
SELECT_ATHLETE_TEXT = "Выберите спортсмена для привязки аккаунта."
NO_UNLINKED_ATHLETES_TEXT = "Спортсменов без Telegram-аккаунта нет."
LINK_PERMISSION_DENIED_TEXT = "Действие доступно только администратору."
ATHLETE_UNAVAILABLE_TEXT = "Спортсмен уже связан или больше не доступен."
CALLBACK_UNAVAILABLE_TEXT = "Не удалось обработать выбранное действие."
INVITE_CAPTION = "Отсканируйте QR новым Telegram-аккаунтом.\n{deep_link}"


def build_athlete_selection_keyboard(
    athletes: tuple[UnlinkedAthlete, ...],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=athlete.full_name,
                    callback_data=(
                        f"{SELECT_ATHLETE_PREFIX}{athlete.athlete_id}"
                    ),
                )
            ]
            for athlete in athletes
        ]
        + [[build_back_button(NavigationTarget.MENU)]]
    )


@inject
async def handle_list_unlinked_athletes(
    callback: CallbackQuery,
    interactor: FromDishka[ListUnlinkedAthletesInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    try:
        athletes = await interactor(
            ListUnlinkedAthletesQuery(
                actor_telegram_id=callback.from_user.id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await message.answer(
            LINK_PERMISSION_DENIED_TEXT,
            reply_markup=build_single_button_keyboard(build_menu_button()),
        )
        return

    if not athletes:
        await message.answer(
            NO_UNLINKED_ATHLETES_TEXT,
            reply_markup=build_single_button_keyboard(
                build_back_button(NavigationTarget.MENU)
            ),
        )
        return
    await message.answer(
        SELECT_ATHLETE_TEXT,
        reply_markup=build_athlete_selection_keyboard(athletes),
    )


@inject
async def handle_create_athlete_account_link_invite(
    callback: CallbackQuery,
    bot: Bot,
    interactor: FromDishka[CreateAthleteAccountLinkInviteInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    try:
        athlete_id = int(callback.data.removeprefix(SELECT_ATHLETE_PREFIX))
    except ValueError:
        await message.answer(
            CALLBACK_UNAVAILABLE_TEXT,
            reply_markup=build_single_button_keyboard(build_menu_button()),
        )
        return

    bot_user = await bot.get_me()
    if bot_user.username is None:
        await message.answer(
            CALLBACK_UNAVAILABLE_TEXT,
            reply_markup=build_single_button_keyboard(build_menu_button()),
        )
        return

    try:
        result = await interactor(
            CreateAthleteAccountLinkInviteCommand(
                actor_telegram_id=callback.from_user.id,
                athlete_id=athlete_id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await message.answer(
            LINK_PERMISSION_DENIED_TEXT,
            reply_markup=build_single_button_keyboard(build_menu_button()),
        )
        return
    except (AthleteAlreadyLinkedError, AthleteNotFoundError):
        await message.answer(
            ATHLETE_UNAVAILABLE_TEXT,
            reply_markup=build_single_button_keyboard(
                build_back_button(NavigationTarget.ATHLETE_LINK_LIST)
            ),
        )
        return

    deep_link = build_bot_start_deep_link(
        result.raw_token,
        bot_user.username,
    )
    qr_png = generate_qr_png(deep_link)
    await message.answer_photo(
        BufferedInputFile(qr_png, filename="athlete-account-link.png"),
        caption=INVITE_CAPTION.format(deep_link=deep_link),
        reply_markup=build_single_button_keyboard(build_menu_button()),
    )


def create_account_link_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_list_unlinked_athletes,
        F.data == LINK_ACCOUNT_ACTION,
    )
    router.callback_query.register(
        handle_list_unlinked_athletes,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.ATHLETE_LINK_LIST)
        ),
    )
    router.callback_query.register(
        handle_create_athlete_account_link_invite,
        F.data.startswith(SELECT_ATHLETE_PREFIX),
    )
    return router
