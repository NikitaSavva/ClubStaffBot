from enum import StrEnum
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import (
    ListAthleteSelectionInteractor,
)
from application.attendance import (
    ConfirmAttendanceCommand,
    ConfirmAttendanceInteractor,
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
    SelectableAttendanceSession,
)
from application.identity import GetUserMenuContextInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from domain.attendance import AttendanceSource
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
    start_athlete_selector,
)
from presentation.telegram.handlers.menu import (
    set_administrative_navigation_context,
    show_active_role_panel,
)
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.navigation import build_menu_button
from presentation.telegram.screen import (
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import (
    AthleteSelectorStates,
    ManualAttendanceStates,
)
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
)

MANUAL_ATTENDANCE_ACTION = "administrator.confirm_attendance"
PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
ATHLETE_UNAVAILABLE_TEXT = "Выбранный спортсмен больше не доступен."
SESSION_UNAVAILABLE_TEXT = "Выбранная тренировка недоступна для отметки."
ATTENDANCE_CANCELLED_TEXT = "Отметка посещения отменена."


class ManualAttendanceAction(StrEnum):
    SESSION = "session"
    CANCELLED = "cancelled"
    CONFIRM = "confirm"
    NEXT = "next"
    BACK_SELECTOR = "back_selector"
    BACK_SESSIONS = "back_sessions"


class ManualAttendanceCallback(CallbackData, prefix="manual"):
    action: ManualAttendanceAction
    value: int


@inject
async def handle_begin_manual_attendance(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await set_administrative_navigation_context(state)
    await start_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=AthleteSelectionPurpose.ATTENDANCE,
        interactor=interactor,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_select_attendance_athlete(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    attendance_interactor: FromDishka[ConfirmAttendanceInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    athlete_public_id = _parse_public_id(callback_data.value)
    if athlete_public_id is None:
        await _show_terminal_text(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return
    result = await _confirm(
        actor_telegram_id=callback.from_user.id,
        athlete_public_id=athlete_public_id,
        attendance_interactor=attendance_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if result is None:
        return
    if result.outcome is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED:
        await set_flow_context(
            state,
            {"athlete_public_id": str(athlete_public_id)},
        )
        await _show_session_selection(message, state, result, renderer)
        return
    await _show_terminal_result(message, state, result, renderer)


@inject
async def handle_select_attendance_session(
    callback: CallbackQuery,
    callback_data: ManualAttendanceCallback,
    state: FSMContext,
    attendance_interactor: FromDishka[ConfirmAttendanceInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    prepared = await _prepare_session_selection(
        actor_telegram_id=callback.from_user.id,
        state=state,
        attendance_interactor=attendance_interactor,
        message=message,
        renderer=renderer,
    )
    if prepared is None:
        return
    athlete_public_id, result = prepared
    if result.outcome is not ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED:
        await _show_terminal_result(message, state, result, renderer)
        return
    selected = _find_session(result.sessions, callback_data.value)
    if selected is None or not selected.selectable:
        await _show_terminal_text(
            message,
            state,
            renderer,
            SESSION_UNAVAILABLE_TEXT,
        )
        return
    await set_flow_context(
        state,
        {
            "athlete_public_id": str(athlete_public_id),
            "training_session_id": selected.training_session_id,
        },
    )
    await state.set_state(ManualAttendanceStates.confirming_session)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=_confirmation_text(result, selected),
            reply_markup=build_confirmation_keyboard(),
        ),
        editable_message=message,
    )


@inject
async def handle_cancelled_attendance_session(
    callback: CallbackQuery,
    state: FSMContext,
    attendance_interactor: FromDishka[ConfirmAttendanceInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    prepared = await _prepare_session_selection(
        actor_telegram_id=callback.from_user.id,
        state=state,
        attendance_interactor=attendance_interactor,
        message=message,
        renderer=renderer,
    )
    if prepared is None:
        return
    _, result = prepared
    if result.outcome is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED:
        await _show_session_selection(
            message,
            state,
            result,
            renderer,
            notice="Эта тренировка отменена. Отметить посещение нельзя.",
        )
        return
    await _show_terminal_result(message, state, result, renderer)


@inject
async def handle_confirm_manual_attendance(
    callback: CallbackQuery,
    state: FSMContext,
    attendance_interactor: FromDishka[ConfirmAttendanceInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    context = await get_flow_context(state)
    athlete_public_id = _context_public_id(context)
    training_session_id = _context_id(context, "training_session_id")
    if athlete_public_id is None or training_session_id is None:
        await _show_terminal_text(
            message,
            state,
            renderer,
            SESSION_UNAVAILABLE_TEXT,
        )
        return
    result = await _confirm(
        actor_telegram_id=callback.from_user.id,
        athlete_public_id=athlete_public_id,
        attendance_interactor=attendance_interactor,
        message=message,
        state=state,
        renderer=renderer,
        training_session_id=training_session_id,
    )
    if result is not None:
        await _show_terminal_result(message, state, result, renderer)


@inject
async def handle_back_to_attendance_sessions(
    callback: CallbackQuery,
    state: FSMContext,
    attendance_interactor: FromDishka[ConfirmAttendanceInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    prepared = await _prepare_session_selection(
        actor_telegram_id=callback.from_user.id,
        state=state,
        attendance_interactor=attendance_interactor,
        message=message,
        renderer=renderer,
    )
    if prepared is None:
        return
    _, result = prepared
    if result.outcome is ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED:
        await _show_session_selection(message, state, result, renderer)
        return
    await _show_terminal_result(message, state, result, renderer)


@inject
async def handle_back_to_attendance_selector(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await start_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=AthleteSelectionPurpose.ATTENDANCE,
        interactor=interactor,
        renderer=renderer,
        mode=RenderMode.EDIT,
    )


@inject
async def handle_cancel_manual_attendance(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    await clear_flow_context(state)
    if telegram_user is None:
        return
    await show_active_role_panel(
        chat_id=message.chat.id,
        telegram_id=telegram_user.id,
        state=state,
        interactor=menu_interactor,
        renderer=renderer,
        notice=ATTENDANCE_CANCELLED_TEXT,
        mode=RenderMode.NEW,
    )


def create_manual_attendance_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_manual_attendance,
        F.data == MANUAL_ATTENDANCE_ACTION,
    )
    router.callback_query.register(
        handle_select_attendance_athlete,
        AthleteSelectorCallback.filter(
            (F.purpose == AthleteSelectionPurpose.ATTENDANCE)
            & (F.action == AthleteSelectorAction.SELECT)
        ),
        AthleteSelectorStates.selecting,
    )
    router.callback_query.register(
        handle_select_attendance_session,
        ManualAttendanceCallback.filter(
            F.action == ManualAttendanceAction.SESSION
        ),
        ManualAttendanceStates.selecting_session,
    )
    router.callback_query.register(
        handle_cancelled_attendance_session,
        ManualAttendanceCallback.filter(
            F.action == ManualAttendanceAction.CANCELLED
        ),
        ManualAttendanceStates.selecting_session,
    )
    router.callback_query.register(
        handle_confirm_manual_attendance,
        ManualAttendanceCallback.filter(
            F.action == ManualAttendanceAction.CONFIRM
        ),
        ManualAttendanceStates.confirming_session,
    )
    router.callback_query.register(
        handle_back_to_attendance_sessions,
        ManualAttendanceCallback.filter(
            F.action == ManualAttendanceAction.BACK_SESSIONS
        ),
        ManualAttendanceStates.confirming_session,
    )
    router.callback_query.register(
        handle_back_to_attendance_selector,
        ManualAttendanceCallback.filter(
            F.action.in_(
                {
                    ManualAttendanceAction.NEXT,
                    ManualAttendanceAction.BACK_SELECTOR,
                }
            )
        ),
        StateFilter(ManualAttendanceStates),
    )
    router.message.register(
        handle_cancel_manual_attendance,
        Command("cancel"),
        StateFilter(ManualAttendanceStates),
    )
    return router


async def _prepare_session_selection(
    *,
    actor_telegram_id: int,
    state: FSMContext,
    attendance_interactor: ConfirmAttendanceInteractor,
    message: Message,
    renderer: TelegramScreenRenderer,
) -> tuple[UUID, ConfirmAttendanceResult] | None:
    athlete_public_id = _context_public_id(await get_flow_context(state))
    if athlete_public_id is None:
        await _show_terminal_text(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return None
    result = await _confirm(
        actor_telegram_id=actor_telegram_id,
        athlete_public_id=athlete_public_id,
        attendance_interactor=attendance_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    return (athlete_public_id, result) if result is not None else None


async def _confirm(
    *,
    actor_telegram_id: int,
    athlete_public_id: UUID,
    attendance_interactor: ConfirmAttendanceInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    training_session_id: int | None = None,
) -> ConfirmAttendanceResult | None:
    try:
        return await attendance_interactor(
            ConfirmAttendanceCommand(
                actor_telegram_id=actor_telegram_id,
                athlete_public_id=athlete_public_id,
                source=AttendanceSource.MANUAL,
                training_session_id=training_session_id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_text(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
        )
    except AthleteNotFoundError:
        await _show_terminal_text(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
    return None


async def _show_session_selection(
    message: Message,
    state: FSMContext,
    result: ConfirmAttendanceResult,
    renderer: TelegramScreenRenderer,
    *,
    notice: str | None = None,
) -> None:
    await state.set_state(ManualAttendanceStates.selecting_session)
    text = (
        "Выберите тренировку\n\n"
        f"{result.athlete.full_name}"
    )
    if not result.sessions:
        text += "\n\nСегодня нет доступных обычных тренировок."
    if notice:
        text = f"{notice}\n\n{text}"
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=text,
            reply_markup=build_session_selection_keyboard(result.sessions),
        ),
        editable_message=message,
    )


def build_session_selection_keyboard(
    sessions: tuple[SelectableAttendanceSession, ...],
) -> InlineKeyboardMarkup:
    rows = []
    for session in sessions:
        action = (
            ManualAttendanceAction.SESSION
            if session.selectable
            else ManualAttendanceAction.CANCELLED
        )
        label = (
            f"{session.starts_at:%H:%M} · {session.sport_direction_name} · "
            f"{session.group_name}"
        )
        if not session.selectable:
            label += " — Отменена"
        rows.append(
            (
                build_callback_button(
                    text=label,
                    callback_data=ManualAttendanceCallback(
                        action=action,
                        value=session.training_session_id,
                    ).pack(),
                ),
            )
        )
    rows.append(
        (
            build_callback_button(
                text="← Назад",
                callback_data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.BACK_SELECTOR,
                    value=0,
                ).pack(),
            ),
        )
    )
    return build_inline_keyboard(*rows)


def build_confirmation_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Отметить",
                callback_data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.CONFIRM,
                    value=0,
                ).pack(),
            ),
        ),
        (
            build_callback_button(
                text="← Назад",
                callback_data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.BACK_SESSIONS,
                    value=0,
                ).pack(),
            ),
        ),
    )


def build_terminal_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Отметить следующий",
                callback_data=ManualAttendanceCallback(
                    action=ManualAttendanceAction.NEXT,
                    value=0,
                ).pack(),
            ),
        ),
        (build_menu_button(),),
    )


async def _show_terminal_result(
    message: Message,
    state: FSMContext,
    result: ConfirmAttendanceResult,
    renderer: TelegramScreenRenderer,
) -> None:
    await set_flow_context(state, {})
    await state.set_state(ManualAttendanceStates.terminal)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=_terminal_text(result),
            reply_markup=build_terminal_keyboard(),
        ),
        editable_message=message,
    )


async def _show_terminal_text(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
) -> None:
    await set_flow_context(state, {})
    await state.set_state(ManualAttendanceStates.terminal)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=text,
            reply_markup=build_terminal_keyboard(),
        ),
        editable_message=message,
    )


def _confirmation_text(
    result: ConfirmAttendanceResult,
    session: SelectableAttendanceSession,
) -> str:
    return (
        "Отметить посещение?\n\n"
        f"{result.athlete.full_name}\n"
        f"{session.sport_direction_name} · {session.group_name}\n"
        f"{session.starts_at:%H:%M}"
    )


def _terminal_text(result: ConfirmAttendanceResult) -> str:
    athlete = result.athlete.full_name
    session = _session_text(result)
    if result.outcome is ConfirmAttendanceOutcome.CONFIRMED:
        base = f"Посещение отмечено\n\n{athlete}{session}"
        if result.subscription_finished:
            return (
                f"{base}\n\nЭто было последнее посещение по абонементу.\n"
                "Для следующей тренировки необходимо выдать новый абонемент."
            )
        remaining = (
            "Без ограничений"
            if result.remaining_visits is None
            else str(result.remaining_visits)
        )
        return f"{base}\n\nОсталось посещений: {remaining}"
    messages = {
        ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION: (
            "Нет активного абонемента",
            "Необходимо оформить новый через «Выдать абонемент».",
        ),
        ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED: (
            "Абонемент истёк",
            "Необходимо оформить новый через «Выдать абонемент».",
        ),
        ConfirmAttendanceOutcome.VISITS_EXHAUSTED: (
            "Посещения закончились",
            "Необходимо выдать новый абонемент.",
        ),
        ConfirmAttendanceOutcome.NO_TRAINING_SESSION: (
            "Сегодня для этой группы нет тренировки.",
            "",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED: (
            "Сегодняшняя тренировка отменена.",
            "Отметить посещение нельзя.",
        ),
        ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS: (
            "Посещение уже отмечено",
            "",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED: (
            "Выбранная тренировка недоступна для отметки посещения.",
            "",
        ),
        ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS: (
            "Для группы найдено несколько тренировок на сегодня.",
            "Невозможно однозначно определить занятие.",
        ),
    }
    try:
        title, detail = messages[result.outcome]
    except KeyError as error:
        raise RuntimeError(
            f"Unexpected manual attendance outcome: {result.outcome}"
        ) from error
    parts = [title, athlete]
    if session:
        parts.append(session.lstrip("\n"))
    if detail:
        parts.append(detail)
    return "\n\n".join(parts)


def _session_text(result: ConfirmAttendanceResult) -> str:
    if result.session is None:
        return ""
    return (
        f"\n{result.session.sport_direction_name} · "
        f"{result.session.group_name}\n{result.session.starts_at:%H:%M}"
    )


def _find_session(
    sessions: tuple[SelectableAttendanceSession, ...],
    training_session_id: int,
) -> SelectableAttendanceSession | None:
    return next(
        (
            session
            for session in sessions
            if session.training_session_id == training_session_id
        ),
        None,
    )


def _context_id(context: dict[str, object], key: str) -> int | None:
    value = context.get(key)
    return value if isinstance(value, int) else None


def _context_public_id(context: dict[str, object]) -> UUID | None:
    value = context.get("athlete_public_id")
    return _parse_public_id(value) if isinstance(value, str) else None


def _parse_public_id(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
