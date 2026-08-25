from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
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
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
    build_back_button,
    build_menu_button,
)
from presentation.telegram.presenters import RolePanel
from presentation.telegram.qr import build_bot_start_deep_link, generate_qr_png
from presentation.telegram.screen import (
    BannerContext,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    set_flow_context,
    set_navigation_context,
)

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
    athlete_rows = tuple(
        (
            build_callback_button(
                text=athlete.full_name,
                callback_data=f"{SELECT_ATHLETE_PREFIX}{athlete.athlete_id}",
            ),
        )
        for athlete in athletes
    )
    return build_inline_keyboard(
        *athlete_rows,
        (build_back_button(NavigationTarget.ROLE_PANEL),),
    )


@inject
async def handle_list_unlinked_athletes(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[ListUnlinkedAthletesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await show_unlinked_athletes(
        chat_id=message.chat.id,
        actor_telegram_id=callback.from_user.id,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=message,
    )


async def show_unlinked_athletes(
    *,
    chat_id: int,
    actor_telegram_id: int,
    state: FSMContext,
    interactor: ListUnlinkedAthletesInteractor,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None = None,
) -> None:
    try:
        athletes = await interactor(
            ListUnlinkedAthletesQuery(
                actor_telegram_id=actor_telegram_id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _set_admin_navigation(state)
        await set_flow_context(state, {})
        await renderer.render(
            state=state,
            chat_id=chat_id,
            screen=_admin_screen(
                LINK_PERMISSION_DENIED_TEXT,
                build_inline_keyboard((build_menu_button(),)),
            ),
            editable_message=editable_message,
        )
        return

    await _set_admin_navigation(state)
    await set_flow_context(state, {})
    if not athletes:
        screen = _admin_screen(
            NO_UNLINKED_ATHLETES_TEXT,
            build_inline_keyboard(
                (build_back_button(NavigationTarget.ROLE_PANEL),)
            ),
        )
    else:
        screen = _admin_screen(
            SELECT_ATHLETE_TEXT,
            build_athlete_selection_keyboard(athletes),
        )
    await renderer.render(
        state=state,
        chat_id=chat_id,
        screen=screen,
        editable_message=editable_message,
    )


@inject
async def handle_create_athlete_account_link_invite(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    interactor: FromDishka[CreateAthleteAccountLinkInviteInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    try:
        athlete_id = int(callback.data.removeprefix(SELECT_ATHLETE_PREFIX))
    except ValueError:
        await _render_callback_unavailable(message, state, renderer)
        return

    bot_user = await bot.get_me()
    if bot_user.username is None:
        await _render_callback_unavailable(message, state, renderer)
        return

    try:
        result = await interactor(
            CreateAthleteAccountLinkInviteCommand(
                actor_telegram_id=callback.from_user.id,
                athlete_id=athlete_id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _set_admin_navigation(state)
        await set_flow_context(state, {})
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                LINK_PERMISSION_DENIED_TEXT,
                build_inline_keyboard((build_menu_button(),)),
            ),
            editable_message=message,
        )
        return
    except (AthleteAlreadyLinkedError, AthleteNotFoundError):
        await _set_admin_navigation(state)
        await set_flow_context(state, {})
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                ATHLETE_UNAVAILABLE_TEXT,
                build_inline_keyboard(
                    (build_back_button(NavigationTarget.ATHLETE_LINK_LIST),)
                ),
            ),
            editable_message=message,
        )
        return

    deep_link = build_bot_start_deep_link(
        result.raw_token,
        bot_user.username,
    )
    qr_png = generate_qr_png(deep_link)
    await _set_admin_navigation(state)
    await set_flow_context(
        state,
        {
            "selected_athlete_id": athlete_id,
            "invite_id": result.invite_id,
        },
    )
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=INVITE_CAPTION.format(deep_link=deep_link),
            media=BufferedInputFile(
                qr_png,
                filename="athlete-account-link.png",
            ),
            media_key=f"athlete-account-link:{result.invite_id}",
            reply_markup=build_inline_keyboard(
                (build_back_button(NavigationTarget.ATHLETE_LINK_LIST),)
            ),
        ),
        editable_message=message,
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


async def _set_admin_navigation(state: FSMContext) -> None:
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_PANEL,
            active_role=RolePanel.ADMINISTRATOR.value,
        ),
    )


async def _render_callback_unavailable(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> None:
    await _set_admin_navigation(state)
    await set_flow_context(state, {})
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            CALLBACK_UNAVAILABLE_TEXT,
            build_inline_keyboard((build_menu_button(),)),
        ),
        editable_message=message,
    )


def _admin_screen(
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        reply_markup=reply_markup,
        banner=BannerContext.ADMIN_PANEL,
    )
