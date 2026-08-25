from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import (
    CreateManualAthleteCommand,
    CreateManualAthleteInteractor,
)
from application.identity import GetUserMenuContextInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
from domain.identity import AthleteFirstNameRequiredError
from presentation.telegram.handlers.menu import show_active_role_panel
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
    build_back_button,
    build_cancel_button,
    build_menu_button,
)
from presentation.telegram.presenters import RolePanel
from presentation.telegram.screen import (
    BannerContext,
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import CreateAthleteStates
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    clear_flow_context,
    get_flow_context,
    set_flow_context,
    set_navigation_context,
)

CREATE_ATHLETE_ACTION = "administrator.create_athlete"
CONFIRM_CREATE_ATHLETE_ACTION = "administrator.create_athlete:confirm"
CREATE_ATHLETE_TITLE = "Добавление спортсмена"
ENTER_FIRST_NAME_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\nВведите имя спортсмена без фамилии."
)
INVALID_FIRST_NAME_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Имя не может быть пустым. Введите имя еще раз."
)
CONFIRM_CREATE_ATHLETE_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Имя: {first_name}\n\n"
    "Проверьте данные."
)
CREATE_ATHLETE_CANCELLED_TEXT = "Создание спортсмена отменено."
CREATE_ATHLETE_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору."
)
CREATE_ATHLETE_SUCCESS_TEXT = "Спортсмен {first_name} создан."


def build_create_athlete_confirmation_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Создать",
                callback_data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        ),
        (
            build_back_button(NavigationTarget.CREATE_ATHLETE_FIRST_NAME),
            build_cancel_button(),
        ),
    )


@inject
async def handle_begin_create_athlete(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await begin_create_athlete_flow(
        chat_id=message.chat.id,
        state=state,
        renderer=renderer,
        editable_message=message,
    )


async def begin_create_athlete_flow(
    *,
    chat_id: int,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None = None,
) -> None:
    await _set_admin_navigation(state)
    await set_flow_context(state, {})
    await state.set_state(CreateAthleteStates.waiting_for_first_name)
    await renderer.render(
        state=state,
        chat_id=chat_id,
        screen=_admin_screen(
            ENTER_FIRST_NAME_TEXT,
            build_inline_keyboard((build_cancel_button(),)),
        ),
        mode=RenderMode.NEW,
        editable_message=editable_message,
    )


@inject
async def handle_cancel_create_athlete(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    await _cancel_create_athlete(
        message=message,
        state=state,
        telegram_id=telegram_user.id if telegram_user is not None else None,
        menu_interactor=menu_interactor,
        renderer=renderer,
        editable_message=None,
    )


@inject
async def handle_cancel_create_athlete_callback(
    callback: CallbackQuery,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await _cancel_create_athlete(
        message=message,
        state=state,
        telegram_id=callback.from_user.id,
        menu_interactor=menu_interactor,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_create_athlete_first_name(
    message: Message,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    first_name = message.text.strip() if message.text is not None else ""
    if telegram_user is None or not first_name:
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                INVALID_FIRST_NAME_TEXT,
                build_inline_keyboard((build_cancel_button(),)),
            ),
            mode=RenderMode.NEW,
        )
        return

    await set_flow_context(state, {"first_name": first_name})
    await state.set_state(CreateAthleteStates.waiting_for_confirmation)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            CONFIRM_CREATE_ATHLETE_TEXT.format(first_name=first_name),
            build_create_athlete_confirmation_keyboard(),
        ),
        mode=RenderMode.NEW,
    )


@inject
async def handle_back_to_create_athlete_first_name(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await set_flow_context(state, {})
    await state.set_state(CreateAthleteStates.waiting_for_first_name)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            ENTER_FIRST_NAME_TEXT,
            build_inline_keyboard((build_cancel_button(),)),
        ),
        mode=RenderMode.EDIT,
        editable_message=message,
    )


@inject
async def handle_confirm_create_athlete(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[CreateManualAthleteInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    flow_context = await get_flow_context(state)
    first_name = flow_context.get("first_name")
    if not isinstance(first_name, str) or not first_name:
        await set_flow_context(state, {})
        await state.set_state(CreateAthleteStates.waiting_for_first_name)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                INVALID_FIRST_NAME_TEXT,
                build_inline_keyboard((build_cancel_button(),)),
            ),
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return

    try:
        result = await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=callback.from_user.id,
                first_name=first_name,
            )
        )
    except AthleteFirstNameRequiredError:
        await set_flow_context(state, {})
        await state.set_state(CreateAthleteStates.waiting_for_first_name)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                INVALID_FIRST_NAME_TEXT,
                build_inline_keyboard((build_cancel_button(),)),
            ),
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await clear_flow_context(state)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(
                CREATE_ATHLETE_PERMISSION_DENIED_TEXT,
                build_inline_keyboard((build_menu_button(),)),
            ),
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return

    await clear_flow_context(state)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            CREATE_ATHLETE_SUCCESS_TEXT.format(first_name=result.first_name),
            build_inline_keyboard((build_menu_button(),)),
        ),
        mode=RenderMode.EDIT,
        editable_message=message,
    )


async def _cancel_create_athlete(
    *,
    message: Message,
    state: FSMContext,
    telegram_id: int | None,
    menu_interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None,
) -> None:
    await clear_flow_context(state)
    if telegram_id is None:
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_admin_screen(CREATE_ATHLETE_CANCELLED_TEXT, None),
            editable_message=editable_message,
        )
        return
    await show_active_role_panel(
        chat_id=message.chat.id,
        telegram_id=telegram_id,
        state=state,
        interactor=menu_interactor,
        renderer=renderer,
        editable_message=editable_message,
        notice=CREATE_ATHLETE_CANCELLED_TEXT,
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
        StateFilter(CreateAthleteStates),
    )
    router.callback_query.register(
        handle_cancel_create_athlete_callback,
        NavigationCallback.filter(
            (F.action == NavigationAction.CANCEL)
            & (F.target == NavigationTarget.ROLE_PANEL)
        ),
        StateFilter(CreateAthleteStates),
    )
    router.callback_query.register(
        handle_back_to_create_athlete_first_name,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.CREATE_ATHLETE_FIRST_NAME)
        ),
        CreateAthleteStates.waiting_for_confirmation,
    )
    router.callback_query.register(
        handle_confirm_create_athlete,
        F.data == CONFIRM_CREATE_ATHLETE_ACTION,
        CreateAthleteStates.waiting_for_confirmation,
    )
    router.message.register(
        handle_create_athlete_first_name,
        CreateAthleteStates.waiting_for_first_name,
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


def _admin_screen(
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        reply_markup=reply_markup,
        banner=BannerContext.ADMIN_PANEL,
    )
