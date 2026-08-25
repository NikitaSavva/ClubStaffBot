import re
from datetime import date, datetime

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
from domain.identity import (
    AthleteBirthDateRequiredError,
    AthleteFirstNameRequiredError,
    AthleteLastNameRequiredError,
)
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
ENTER_FIRST_NAME_TEXT = f"{CREATE_ATHLETE_TITLE}\n\nВведите имя спортсмена."
INVALID_FIRST_NAME_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Имя не может быть пустым. Введите имя еще раз."
)
ENTER_LAST_NAME_TEXT = f"{CREATE_ATHLETE_TITLE}\n\nВведите фамилию спортсмена."
INVALID_LAST_NAME_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Фамилия не может быть пустой. Введите фамилию еще раз."
)
ENTER_BIRTH_DATE_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Введите дату рождения в формате DD.MM.YYYY."
)
INVALID_BIRTH_DATE_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Введите корректную календарную дату в формате DD.MM.YYYY."
)
CONFIRM_CREATE_ATHLETE_TEXT = (
    f"{CREATE_ATHLETE_TITLE}\n\n"
    "Имя: {first_name}\n"
    "Фамилия: {last_name}\n"
    "Дата рождения: {birth_date}\n\n"
    "Проверьте данные."
)
CREATE_ATHLETE_CANCELLED_TEXT = "Создание спортсмена отменено."
CREATE_ATHLETE_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору."
)
CREATE_ATHLETE_SUCCESS_TEXT = "Спортсмен {first_name} {last_name} создан."

_BIRTH_DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def build_create_athlete_confirmation_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Создать",
                callback_data=CONFIRM_CREATE_ATHLETE_ACTION,
            ),
        ),
        (
            build_back_button(NavigationTarget.CREATE_ATHLETE_BIRTH_DATE),
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

    await _set_admin_navigation(state)
    await set_flow_context(state, {})
    await _show_first_name_step(
        message=message,
        state=state,
        renderer=renderer,
        mode=RenderMode.NEW,
        editable_message=message,
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
    first_name = _message_text(message)
    if message.from_user is None or not first_name:
        await _render_prompt(
            message=message,
            state=state,
            renderer=renderer,
            text=INVALID_FIRST_NAME_TEXT,
            back_target=None,
            mode=RenderMode.NEW,
        )
        return

    await set_flow_context(state, {"first_name": first_name})
    await state.set_state(CreateAthleteStates.waiting_for_last_name)
    await _render_prompt(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_LAST_NAME_TEXT,
        back_target=NavigationTarget.CREATE_ATHLETE_FIRST_NAME,
        mode=RenderMode.NEW,
    )


@inject
async def handle_create_athlete_last_name(
    message: Message,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    flow_context = await get_flow_context(state)
    first_name = flow_context.get("first_name")
    if not isinstance(first_name, str) or not first_name:
        await set_flow_context(state, {})
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.NEW,
        )
        return

    last_name = _message_text(message)
    if message.from_user is None or not last_name:
        await _render_prompt(
            message=message,
            state=state,
            renderer=renderer,
            text=INVALID_LAST_NAME_TEXT,
            back_target=NavigationTarget.CREATE_ATHLETE_FIRST_NAME,
            mode=RenderMode.NEW,
        )
        return

    await set_flow_context(
        state,
        {"first_name": first_name, "last_name": last_name},
    )
    await state.set_state(CreateAthleteStates.waiting_for_birth_date)
    await _render_prompt(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_BIRTH_DATE_TEXT,
        back_target=NavigationTarget.CREATE_ATHLETE_LAST_NAME,
        mode=RenderMode.NEW,
    )


@inject
async def handle_create_athlete_birth_date(
    message: Message,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    flow_context = await get_flow_context(state)
    first_name = flow_context.get("first_name")
    last_name = flow_context.get("last_name")
    if not isinstance(first_name, str) or not isinstance(last_name, str):
        await set_flow_context(state, {})
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.NEW,
        )
        return

    birth_date = parse_birth_date(_message_text(message))
    if birth_date is None:
        await _render_prompt(
            message=message,
            state=state,
            renderer=renderer,
            text=INVALID_BIRTH_DATE_TEXT,
            back_target=NavigationTarget.CREATE_ATHLETE_LAST_NAME,
            mode=RenderMode.NEW,
        )
        return

    await set_flow_context(
        state,
        {
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": birth_date.isoformat(),
        },
    )
    await state.set_state(CreateAthleteStates.waiting_for_confirmation)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            _confirmation_text(first_name, last_name, birth_date),
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
    await _show_first_name_step(
        message=message,
        state=state,
        renderer=renderer,
        mode=RenderMode.EDIT,
        editable_message=message,
    )


@inject
async def handle_back_to_create_athlete_last_name(
    callback: CallbackQuery,
    state: FSMContext,
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
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return
    await set_flow_context(state, {"first_name": first_name})
    await state.set_state(CreateAthleteStates.waiting_for_last_name)
    await _render_prompt(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_LAST_NAME_TEXT,
        back_target=NavigationTarget.CREATE_ATHLETE_FIRST_NAME,
        mode=RenderMode.EDIT,
        editable_message=message,
    )


@inject
async def handle_back_to_create_athlete_birth_date(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    flow_context = await get_flow_context(state)
    first_name = flow_context.get("first_name")
    last_name = flow_context.get("last_name")
    if not isinstance(first_name, str) or not isinstance(last_name, str):
        await set_flow_context(state, {})
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return
    await set_flow_context(
        state,
        {"first_name": first_name, "last_name": last_name},
    )
    await state.set_state(CreateAthleteStates.waiting_for_birth_date)
    await _render_prompt(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_BIRTH_DATE_TEXT,
        back_target=NavigationTarget.CREATE_ATHLETE_LAST_NAME,
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

    form_data = await _get_complete_form_data(state)
    if form_data is None:
        await set_flow_context(state, {})
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.EDIT,
            editable_message=message,
        )
        return
    first_name, last_name, birth_date = form_data

    try:
        result = await interactor(
            CreateManualAthleteCommand(
                actor_telegram_id=callback.from_user.id,
                first_name=first_name,
                last_name=last_name,
                birth_date=birth_date,
            )
        )
    except (
        AthleteBirthDateRequiredError,
        AthleteFirstNameRequiredError,
        AthleteLastNameRequiredError,
    ):
        await set_flow_context(state, {})
        await _show_first_name_step(
            message=message,
            state=state,
            renderer=renderer,
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
            CREATE_ATHLETE_SUCCESS_TEXT.format(
                first_name=result.first_name,
                last_name=result.last_name,
            ),
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
        CreateAthleteStates.waiting_for_last_name,
    )
    router.callback_query.register(
        handle_back_to_create_athlete_last_name,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.CREATE_ATHLETE_LAST_NAME)
        ),
        CreateAthleteStates.waiting_for_birth_date,
    )
    router.callback_query.register(
        handle_back_to_create_athlete_birth_date,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.CREATE_ATHLETE_BIRTH_DATE)
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
    router.message.register(
        handle_create_athlete_last_name,
        CreateAthleteStates.waiting_for_last_name,
    )
    router.message.register(
        handle_create_athlete_birth_date,
        CreateAthleteStates.waiting_for_birth_date,
    )
    return router


def parse_birth_date(value: str) -> date | None:
    if _BIRTH_DATE_PATTERN.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


async def _get_complete_form_data(
    state: FSMContext,
) -> tuple[str, str, date] | None:
    flow_context = await get_flow_context(state)
    first_name = flow_context.get("first_name")
    last_name = flow_context.get("last_name")
    raw_birth_date = flow_context.get("birth_date")
    if (
        not isinstance(first_name, str)
        or not first_name
        or not isinstance(last_name, str)
        or not last_name
        or not isinstance(raw_birth_date, str)
    ):
        return None
    try:
        birth_date = date.fromisoformat(raw_birth_date)
    except ValueError:
        return None
    return first_name, last_name, birth_date


async def _show_first_name_step(
    *,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    mode: RenderMode,
    editable_message: Message | None = None,
) -> None:
    await state.set_state(CreateAthleteStates.waiting_for_first_name)
    await _render_prompt(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_FIRST_NAME_TEXT,
        back_target=None,
        mode=mode,
        editable_message=editable_message,
    )


async def _render_prompt(
    *,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    back_target: NavigationTarget | None,
    mode: RenderMode,
    editable_message: Message | None = None,
) -> None:
    buttons = [build_cancel_button()]
    if back_target is not None:
        buttons.insert(0, build_back_button(back_target))
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=_admin_screen(
            text,
            build_inline_keyboard(tuple(buttons)),
        ),
        mode=mode,
        editable_message=editable_message,
    )


async def _set_admin_navigation(state: FSMContext) -> None:
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_PANEL,
            active_role=RolePanel.ADMINISTRATOR.value,
        ),
    )


def _confirmation_text(
    first_name: str,
    last_name: str,
    birth_date: date,
) -> str:
    return CONFIRM_CREATE_ATHLETE_TEXT.format(
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date.strftime("%d.%m.%Y"),
    )


def _message_text(message: Message) -> str:
    return message.text.strip() if message.text is not None else ""


def _admin_screen(
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        reply_markup=reply_markup,
        banner=BannerContext.ADMIN_PANEL,
    )
