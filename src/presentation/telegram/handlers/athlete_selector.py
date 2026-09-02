from enum import StrEnum

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import (
    AthleteSearch,
    AthleteSearchKind,
    AthleteSelectionPage,
    ListAthleteSelectionInteractor,
    ListAthleteSelectionQuery,
)
from application.identity import GetUserMenuContextInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
from presentation.telegram.handlers.menu import show_active_role_panel
from presentation.telegram.input_cleanup import cleanup_accepted_user_input
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.navigation import build_menu_button
from presentation.telegram.presenters.athletes import format_athlete_label
from presentation.telegram.screen import (
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import AthleteSelectorStates
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
)

PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
SEARCH_PROMPT_TEXT = (
    "Поиск спортсмена\n\n"
    "Введите фамилию или Telegram username с @.\n\n"
    "Примеры:\nИванов\n@ivanov"
)
INVALID_SURNAME_TEXT = (
    "Поиск спортсмена\n\n"
    "Фамилия не может быть пустой. Введите фамилию ещё раз."
)
INVALID_USERNAME_TEXT = (
    "Поиск спортсмена\n\n"
    "Некорректный Telegram username. Введите username с одним символом @."
)
NO_RESULTS_TEXT = (
    "Поиск спортсмена\n\n"
    "Спортсмены не найдены.\n"
    "Введите другой запрос."
)


class AthleteSelectionPurpose(StrEnum):
    ATTENDANCE = "attendance"
    SUBSCRIPTION = "subscription"


class AthleteSelectorAction(StrEnum):
    SELECT = "select"
    PAGE = "page"
    SEARCH = "search"
    LIST = "list"
    RETURN = "return"


class AthleteSelectorCallback(CallbackData, prefix="athlete"):
    purpose: AthleteSelectionPurpose
    action: AthleteSelectorAction
    value: str


def parse_athlete_search_input(value: str) -> AthleteSearch | None:
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.startswith("@"):
        return AthleteSearch(
            kind=AthleteSearchKind.SURNAME,
            value=normalized,
        )
    username = normalized.removeprefix("@").strip()
    if (
        not username
        or "@" in username
        or any(character.isspace() for character in username)
    ):
        return None
    return AthleteSearch(
        kind=AthleteSearchKind.TELEGRAM_USERNAME,
        value=username,
    )


async def start_athlete_selector(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    purpose: AthleteSelectionPurpose,
    interactor: ListAthleteSelectionInteractor,
    renderer: TelegramScreenRenderer,
    mode: RenderMode,
) -> None:
    await set_flow_context(
        state,
        {
            "selector_purpose": purpose.value,
            "selector_page": 0,
        },
    )
    await show_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=actor_telegram_id,
        purpose=purpose,
        interactor=interactor,
        renderer=renderer,
        mode=mode,
    )


async def show_athlete_selector(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    purpose: AthleteSelectionPurpose,
    interactor: ListAthleteSelectionInteractor,
    renderer: TelegramScreenRenderer,
    mode: RenderMode = RenderMode.EDIT,
    page: int | None = None,
    clear_search: bool = False,
) -> None:
    context = await get_flow_context(state)
    current_purpose = _purpose_from_context(context)
    if current_purpose is not purpose:
        await _show_unavailable(message, state, renderer, mode=mode)
        return
    target_page = page if page is not None else _page_from_context(context)
    search = None if clear_search else _search_from_context(context)
    try:
        result = await interactor(
            ListAthleteSelectionQuery(
                actor_telegram_id=actor_telegram_id,
                page=target_page,
                search=search,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_unavailable(message, state, renderer, mode=mode)
        return

    await _render_selector_result(
        message=message,
        state=state,
        purpose=purpose,
        result=result,
        search=search,
        renderer=renderer,
        mode=mode,
    )


def build_athlete_selector_keyboard(
    *,
    purpose: AthleteSelectionPurpose,
    result: AthleteSelectionPage,
    search: AthleteSearch | None,
) -> InlineKeyboardMarkup:
    rows: list[tuple[InlineKeyboardButton, ...]] = [
        (
            build_callback_button(
                text=format_athlete_label(athlete),
                callback_data=AthleteSelectorCallback(
                    purpose=purpose,
                    action=AthleteSelectorAction.SELECT,
                    value=(
                        str(athlete.athlete_public_id)
                        if purpose is AthleteSelectionPurpose.ATTENDANCE
                        else str(athlete.athlete_id)
                    ),
                ).pack(),
            ),
        )
        for athlete in result.items
    ]
    pagination = []
    if result.has_previous:
        pagination.append(
            build_callback_button(
                text="← Предыдущая",
                callback_data=AthleteSelectorCallback(
                    purpose=purpose,
                    action=AthleteSelectorAction.PAGE,
                    value=str(result.page - 1),
                ).pack(),
            )
        )
    if result.has_next:
        pagination.append(
            build_callback_button(
                text="Следующая →",
                callback_data=AthleteSelectorCallback(
                    purpose=purpose,
                    action=AthleteSelectorAction.PAGE,
                    value=str(result.page + 1),
                ).pack(),
            )
        )
    if pagination:
        rows.append(tuple(pagination))
    rows.append(
        (
            build_callback_button(
                text="🔎 Поиск",
                callback_data=AthleteSelectorCallback(
                    purpose=purpose,
                    action=AthleteSelectorAction.SEARCH,
                    value="0",
                ).pack(),
            ),
        )
    )
    if search is not None:
        rows.append(
            (
                build_callback_button(
                    text="← Назад",
                    callback_data=AthleteSelectorCallback(
                        purpose=purpose,
                        action=AthleteSelectorAction.LIST,
                        value="0",
                    ).pack(),
                ),
            )
        )
    else:
        rows.append((build_menu_button(),))
    return build_inline_keyboard(*rows)


def _search_keyboard(
    purpose: AthleteSelectionPurpose,
) -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Отмена",
                callback_data=AthleteSelectorCallback(
                    purpose=purpose,
                    action=AthleteSelectorAction.RETURN,
                    value="0",
                ).pack(),
            ),
        )
    )


async def _render_selector_result(
    *,
    message: Message,
    state: FSMContext,
    purpose: AthleteSelectionPurpose,
    result: AthleteSelectionPage,
    search: AthleteSearch | None,
    renderer: TelegramScreenRenderer,
    mode: RenderMode,
) -> None:
    await set_flow_context(
        state,
        _selector_context(purpose=purpose, page=result.page, search=search),
    )
    await state.set_state(AthleteSelectorStates.selecting)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=_selector_text(purpose, result, search),
            reply_markup=build_athlete_selector_keyboard(
                purpose=purpose,
                result=result,
                search=search,
            ),
        ),
        mode=mode,
        editable_message=message,
    )


@inject
async def handle_selector_page(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await show_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=callback_data.purpose,
        interactor=interactor,
        renderer=renderer,
        page=_callback_page(callback_data.value),
    )


@inject
async def handle_begin_selector_search(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    context = await get_flow_context(state)
    if (
        not isinstance(message, Message)
        or _purpose_from_context(context) is not callback_data.purpose
    ):
        return
    await state.set_state(AthleteSelectorStates.waiting_for_query)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=SEARCH_PROMPT_TEXT,
            reply_markup=_search_keyboard(callback_data.purpose),
        ),
        mode=RenderMode.NEW,
        editable_message=message,
    )


@inject
async def handle_clear_selector_search(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await show_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=callback_data.purpose,
        interactor=interactor,
        renderer=renderer,
        page=0,
        clear_search=True,
    )


@inject
async def handle_return_to_selector(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await show_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=callback_data.purpose,
        interactor=interactor,
        renderer=renderer,
        page=0,
        clear_search=True,
    )


@inject
async def handle_selector_search_input(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    context = await get_flow_context(state)
    purpose = _purpose_from_context(context)
    raw_value = message.text or ""
    search = parse_athlete_search_input(raw_value)
    if purpose is None:
        await _show_unavailable(message, state, renderer, mode=RenderMode.NEW)
        return
    if search is None:
        invalid_text = (
            INVALID_USERNAME_TEXT
            if raw_value.strip().startswith("@")
            else INVALID_SURNAME_TEXT
        )
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=TelegramScreen(
                text=invalid_text,
                reply_markup=_search_keyboard(purpose),
            ),
        )
        return

    try:
        result = await interactor(
            ListAthleteSelectionQuery(
                actor_telegram_id=(
                    message.from_user.id
                    if message.from_user is not None
                    else 0
                ),
                page=0,
                search=search,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_unavailable(
            message,
            state,
            renderer,
            mode=RenderMode.NEW,
        )
        return
    await cleanup_accepted_user_input(message)
    if not result.items:
        await set_flow_context(
            state,
            {
                "selector_purpose": purpose.value,
                "selector_page": 0,
            },
        )
        await state.set_state(AthleteSelectorStates.waiting_for_query)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=TelegramScreen(
                text=NO_RESULTS_TEXT,
                reply_markup=_search_keyboard(purpose),
            ),
        )
        return
    await _render_selector_result(
        message=message,
        state=state,
        purpose=purpose,
        result=result,
        search=search,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_cancel_athlete_selector(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    context = await get_flow_context(state)
    purpose = _purpose_from_context(context)
    telegram_user = message.from_user
    await clear_flow_context(state)
    if telegram_user is None:
        return
    notice = (
        "Выдача абонемента отменена."
        if purpose is AthleteSelectionPurpose.SUBSCRIPTION
        else "Отметка посещения отменена."
    )
    await show_active_role_panel(
        chat_id=message.chat.id,
        telegram_id=telegram_user.id,
        state=state,
        interactor=menu_interactor,
        renderer=renderer,
        notice=notice,
        mode=RenderMode.NEW,
    )


def create_athlete_selector_router() -> Router:
    router = Router(name=__name__)
    router.message.register(
        handle_cancel_athlete_selector,
        Command("cancel"),
        AthleteSelectorStates.selecting,
    )
    router.message.register(
        handle_cancel_athlete_selector,
        Command("cancel"),
        AthleteSelectorStates.waiting_for_query,
    )
    router.callback_query.register(
        handle_selector_page,
        AthleteSelectorCallback.filter(
            F.action == AthleteSelectorAction.PAGE
        ),
        AthleteSelectorStates.selecting,
    )
    router.callback_query.register(
        handle_begin_selector_search,
        AthleteSelectorCallback.filter(
            F.action == AthleteSelectorAction.SEARCH
        ),
        AthleteSelectorStates.selecting,
    )
    router.callback_query.register(
        handle_clear_selector_search,
        AthleteSelectorCallback.filter(
            F.action == AthleteSelectorAction.LIST
        ),
        AthleteSelectorStates.selecting,
    )
    router.callback_query.register(
        handle_return_to_selector,
        AthleteSelectorCallback.filter(
            F.action == AthleteSelectorAction.RETURN
        ),
        AthleteSelectorStates.waiting_for_query,
    )
    router.message.register(
        handle_selector_search_input,
        AthleteSelectorStates.waiting_for_query,
    )
    return router


def _selector_text(
    purpose: AthleteSelectionPurpose,
    result: AthleteSelectionPage,
    search: AthleteSearch | None,
) -> str:
    title = (
        "Отметить вход"
        if purpose is AthleteSelectionPurpose.ATTENDANCE
        else "Выдача абонемента"
    )
    if search is not None:
        heading = "Результаты поиска"
        if not result.items:
            return f"{heading}\n\n{NO_RESULTS_TEXT}"
        return f"{heading}\n\nВыберите спортсмена:"
    if not result.items:
        return f"{title}\n\nСпортсмены не найдены."
    return f"{title}\n\nВыберите спортсмена:"


def _selector_context(
    *,
    purpose: AthleteSelectionPurpose,
    page: int,
    search: AthleteSearch | None,
) -> dict[str, object]:
    context: dict[str, object] = {
        "selector_purpose": purpose.value,
        "selector_page": page,
    }
    if search is not None:
        context.update(
            {
                "selector_search_kind": search.kind.value,
                "selector_search_value": search.value,
            }
        )
    return context


def _purpose_from_context(
    context: dict[str, object],
) -> AthleteSelectionPurpose | None:
    try:
        return AthleteSelectionPurpose(str(context["selector_purpose"]))
    except (KeyError, ValueError):
        return None


def _page_from_context(context: dict[str, object]) -> int:
    page = context.get("selector_page")
    return page if isinstance(page, int) and page >= 0 else 0


def _callback_page(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _search_from_context(
    context: dict[str, object],
) -> AthleteSearch | None:
    kind = context.get("selector_search_kind")
    value = context.get("selector_search_value")
    if not isinstance(kind, str) or not isinstance(value, str) or not value:
        return None
    try:
        return AthleteSearch(kind=AthleteSearchKind(kind), value=value)
    except ValueError:
        return None


async def _show_unavailable(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    *,
    mode: RenderMode,
) -> None:
    await clear_flow_context(state)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=PERMISSION_DENIED_TEXT,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
        ),
        mode=mode,
        editable_message=message,
    )
