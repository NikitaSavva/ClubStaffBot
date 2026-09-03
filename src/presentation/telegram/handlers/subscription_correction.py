import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import ListAthleteSelectionInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from application.subscriptions import (
    CorrectSubscriptionCommand,
    CorrectSubscriptionInteractor,
    CorrectSubscriptionOutcome,
    GetLatestAthleteSubscriptionInteractor,
    GetLatestAthleteSubscriptionQuery,
    GetLatestAthleteSubscriptionResult,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    InvalidRemainingVisitsError,
    InvalidSubscriptionExpirationError,
    LatestSubscriptionChangedError,
    LimitedSubscriptionRemainingVisitsRequiredError,
    SubscriptionNotFoundError,
    SubscriptionPlanNotFoundError,
    UnlimitedSubscriptionRemainingVisitsForbiddenError,
)
from domain.subscriptions import SubscriptionStatus
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
    start_athlete_selector,
)
from presentation.telegram.handlers.menu import (
    set_administrative_navigation_context,
)
from presentation.telegram.input_cleanup import cleanup_accepted_user_input
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
from presentation.telegram.presenters.subscriptions import (
    format_latest_subscription_card,
    format_subscription_status,
)
from presentation.telegram.screen import (
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import (
    AthleteSelectorStates,
    SubscriptionCorrectionStates,
)
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
    update_flow_context,
)

VIEW_SUBSCRIPTION_ACTION = "administrator.view_subscription"
TITLE = "Корректировка абонемента"
PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
ATHLETE_UNAVAILABLE_TEXT = "Выбранный спортсмен больше не доступен."
SUBSCRIPTION_UNAVAILABLE_TEXT = "Выбранный абонемент больше не доступен."
STALE_SUBSCRIPTION_TEXT = (
    "Абонемент изменился. Откройте данные спортсмена заново."
)
ACTIVE_CONFLICT_TEXT = "У спортсмена уже есть другой активный абонемент."
NO_CHANGES_TEXT = "Изменений нет."
SUCCESS_TEXT = "Абонемент скорректирован."
INVALID_REMAINING_TEXT = (
    "Некорректный остаток. Введите целое число не меньше 0."
)
INVALID_EXPIRES_AT_TEXT = (
    "Некорректная дата. Введите дату окончания в формате ДД.ММ.ГГГГ."
)

_DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{4}")


class SubscriptionCorrectionAction(StrEnum):
    BEGIN = "begin"
    EDIT_REMAINING = "remaining"
    EDIT_EXPIRES_AT = "expires"
    EDIT_STATUS = "status"
    SET_STATUS = "set_status"
    REVIEW = "review"
    CONFIRM = "confirm"
    REOPEN = "reopen"


class SubscriptionCorrectionCallback(CallbackData, prefix="sub_correct"):
    action: SubscriptionCorrectionAction
    value: str


@dataclass(frozen=True, slots=True)
class CorrectionDraft:
    athlete_id: int
    subscription_id: int
    athlete_full_name: str
    is_unlimited: bool
    original_remaining_visits: int | None
    original_expires_at: datetime
    original_status: SubscriptionStatus
    remaining_visits_is_set: bool
    remaining_visits: int | None
    expires_at: datetime | None
    status: SubscriptionStatus | None

    @property
    def final_remaining_visits(self) -> int | None:
        if self.remaining_visits_is_set:
            return self.remaining_visits
        return self.original_remaining_visits

    @property
    def final_expires_at(self) -> datetime:
        return self.expires_at or self.original_expires_at

    @property
    def final_status(self) -> SubscriptionStatus:
        return self.status or self.original_status


@inject
async def handle_begin_subscription_view(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthleteSelectionInteractor],
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
        purpose=AthleteSelectionPurpose.SUBSCRIPTION_VIEW,
        interactor=athletes_interactor,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_select_subscription_athlete(
    callback: CallbackQuery,
    callback_data: AthleteSelectorCallback,
    state: FSMContext,
    interactor: FromDishka[GetLatestAthleteSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    athlete_id = _parse_positive_int(callback_data.value)
    if not isinstance(message, Message) or athlete_id is None:
        return
    await _show_card(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete_id=athlete_id,
        interactor=interactor,
        renderer=renderer,
        club_timezone=club_timezone,
        mode=RenderMode.NEW,
    )


@inject
async def handle_begin_correction(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetLatestAthleteSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    context = await get_flow_context(state)
    athlete_id = _context_int(context, "athlete_id")
    subscription_id = _context_int(context, "subscription_id")
    if (
        not isinstance(message, Message)
        or athlete_id is None
        or subscription_id is None
    ):
        return
    try:
        result = await _load_latest(
            actor_telegram_id=callback.from_user.id,
            athlete_id=athlete_id,
            interactor=interactor,
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(message, state, renderer, PERMISSION_DENIED_TEXT)
        return
    except AthleteNotFoundError:
        await _show_terminal_error(message, state, renderer, ATHLETE_UNAVAILABLE_TEXT)
        return
    if result.latest is None or result.latest.subscription_id != subscription_id:
        await _render_reopen_screen(message, state, renderer)
        return
    await _set_draft_context(state, result)
    await _show_draft(
        message=message,
        state=state,
        renderer=renderer,
        club_timezone=club_timezone,
    )


@inject
async def handle_edit_remaining_visits(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    draft = await _get_draft(state)
    if not isinstance(message, Message) or draft is None:
        return
    if draft.is_unlimited:
        await _show_draft(
            message=message,
            state=state,
            renderer=renderer,
            club_timezone=club_timezone,
            notice=(
                "Для безлимитного абонемента остаток посещений не применяется."
            ),
        )
        return
    await state.set_state(
        SubscriptionCorrectionStates.waiting_for_remaining_visits
    )
    await _render(
        message,
        state,
        renderer,
        (
            f"{TITLE}\n\nСпортсмен:\n{draft.athlete_full_name}\n\n"
            "Введите остаток посещений — целое число не меньше 0."
        ),
        _prompt_keyboard(),
    )


@inject
async def handle_remaining_visits_input(
    message: Message,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    draft = await _get_draft(state)
    raw_value = (message.text or "").strip()
    if draft is None or draft.is_unlimited:
        return
    if not raw_value.isascii() or not raw_value.isdigit():
        await _render(
            message,
            state,
            renderer,
            f"{TITLE}\n\n{INVALID_REMAINING_TEXT}",
            _prompt_keyboard(),
            mode=RenderMode.NEW,
        )
        return
    remaining_visits = int(raw_value)
    await update_flow_context(
        state,
        remaining_visits_is_set=True,
        remaining_visits=remaining_visits,
    )
    await cleanup_accepted_user_input(message)
    await _show_draft(
        message=message,
        state=state,
        renderer=renderer,
        club_timezone=club_timezone,
    )


@inject
async def handle_edit_expires_at(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    draft = await _get_draft(state)
    if not isinstance(message, Message) or draft is None:
        return
    await state.set_state(SubscriptionCorrectionStates.waiting_for_expires_at)
    await _render(
        message,
        state,
        renderer,
        (
            f"{TITLE}\n\nСпортсмен:\n{draft.athlete_full_name}\n\n"
            "Введите дату окончания в формате ДД.ММ.ГГГГ."
        ),
        _prompt_keyboard(),
    )


@inject
async def handle_expires_at_input(
    message: Message,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    draft = await _get_draft(state)
    corrected = (
        parse_corrected_expires_at(
            message.text or "",
            original=draft.original_expires_at,
            club_timezone=club_timezone,
        )
        if draft is not None
        else None
    )
    if draft is None:
        return
    if corrected is None:
        await _render(
            message,
            state,
            renderer,
            f"{TITLE}\n\n{INVALID_EXPIRES_AT_TEXT}",
            _prompt_keyboard(),
            mode=RenderMode.NEW,
        )
        return
    await update_flow_context(state, expires_at=corrected.isoformat())
    await cleanup_accepted_user_input(message)
    await _show_draft(
        message=message,
        state=state,
        renderer=renderer,
        club_timezone=club_timezone,
    )


@inject
async def handle_edit_status(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    draft = await _get_draft(state)
    if not isinstance(message, Message) or draft is None:
        return
    await state.set_state(SubscriptionCorrectionStates.choosing_status)
    await _render(
        message,
        state,
        renderer,
        f"{TITLE}\n\nВыберите новый статус.",
        build_inline_keyboard(
            *(
                (
                    build_callback_button(
                        text=format_subscription_status(status),
                        callback_data=SubscriptionCorrectionCallback(
                            action=SubscriptionCorrectionAction.SET_STATUS,
                            value=status.value,
                        ).pack(),
                    ),
                )
                for status in SubscriptionStatus
            ),
            (
                build_back_button(
                    NavigationTarget.SUBSCRIPTION_CORRECTION_DRAFT
                ),
                build_cancel_button(NavigationTarget.SUBSCRIPTION_VIEW_CARD),
            ),
        ),
    )


@inject
async def handle_set_status(
    callback: CallbackQuery,
    callback_data: SubscriptionCorrectionCallback,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    try:
        status = SubscriptionStatus(callback_data.value)
    except ValueError:
        return
    await update_flow_context(state, status=status.value)
    await _show_draft(
        message=message,
        state=state,
        renderer=renderer,
        club_timezone=club_timezone,
    )


@inject
async def handle_review_correction(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    draft = await _get_draft(state)
    if not isinstance(message, Message) or draft is None:
        return
    changes = _draft_changes(draft, club_timezone)
    if not changes:
        await _show_draft(
            message=message,
            state=state,
            renderer=renderer,
            club_timezone=club_timezone,
            notice=NO_CHANGES_TEXT,
        )
        return
    await state.set_state(SubscriptionCorrectionStates.confirming)
    await _render(
        message,
        state,
        renderer,
        (
            "Подтвердить корректировку абонемента?\n\n"
            + "\n\n".join(changes)
        ),
        build_inline_keyboard(
            (
                build_callback_button(
                    text="Сохранить",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.CONFIRM,
                        value="0",
                    ).pack(),
                ),
            ),
            (
                build_back_button(
                    NavigationTarget.SUBSCRIPTION_CORRECTION_DRAFT
                ),
                build_cancel_button(NavigationTarget.SUBSCRIPTION_VIEW_CARD),
            ),
        ),
    )


@inject
async def handle_confirm_correction(
    callback: CallbackQuery,
    state: FSMContext,
    correct_interactor: FromDishka[CorrectSubscriptionInteractor],
    view_interactor: FromDishka[GetLatestAthleteSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    draft = await _get_draft(state)
    if not isinstance(message, Message) or draft is None:
        return
    try:
        result = await correct_interactor(
            CorrectSubscriptionCommand(
                actor_telegram_id=callback.from_user.id,
                athlete_id=draft.athlete_id,
                subscription_id=draft.subscription_id,
                remaining_visits_is_set=draft.remaining_visits_is_set,
                remaining_visits=draft.remaining_visits,
                expires_at=draft.expires_at,
                status=draft.status,
            )
        )
    except LatestSubscriptionChangedError:
        await _render_reopen_screen(message, state, renderer)
        return
    except ActiveSubscriptionAlreadyExistsError:
        await _show_draft(
            message=message,
            state=state,
            renderer=renderer,
            club_timezone=club_timezone,
            notice=ACTIVE_CONFLICT_TEXT,
        )
        return
    except (
        InvalidRemainingVisitsError,
        LimitedSubscriptionRemainingVisitsRequiredError,
        UnlimitedSubscriptionRemainingVisitsForbiddenError,
        InvalidSubscriptionExpirationError,
    ):
        await _show_draft(
            message=message,
            state=state,
            renderer=renderer,
            club_timezone=club_timezone,
            notice="Проверьте значения корректировки.",
        )
        return
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(message, state, renderer, PERMISSION_DENIED_TEXT)
        return
    except (
        AthleteNotFoundError,
        SubscriptionNotFoundError,
        SubscriptionPlanNotFoundError,
    ):
        await _show_terminal_error(
            message, state, renderer, SUBSCRIPTION_UNAVAILABLE_TEXT
        )
        return

    notice = (
        SUCCESS_TEXT
        if result.outcome is CorrectSubscriptionOutcome.CORRECTED
        else NO_CHANGES_TEXT
    )
    await _show_card(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete_id=draft.athlete_id,
        interactor=view_interactor,
        renderer=renderer,
        club_timezone=club_timezone,
        mode=RenderMode.NEW,
        notice=notice,
    )


@inject
async def handle_back_to_view_athletes(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthleteSelectionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await start_athlete_selector(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        purpose=AthleteSelectionPurpose.SUBSCRIPTION_VIEW,
        interactor=athletes_interactor,
        renderer=renderer,
        mode=RenderMode.EDIT,
    )


@inject
async def handle_back_to_draft(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return
    await _show_draft(
        message=message,
        state=state,
        renderer=renderer,
        club_timezone=club_timezone,
    )


@inject
async def handle_return_to_card(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetLatestAthleteSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    message = callback.message
    athlete_id = _context_int(await get_flow_context(state), "athlete_id")
    if not isinstance(message, Message) or athlete_id is None:
        return
    await _show_card(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete_id=athlete_id,
        interactor=interactor,
        renderer=renderer,
        club_timezone=club_timezone,
        mode=RenderMode.EDIT,
    )


@inject
async def handle_cancel_correction_command(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[GetLatestAthleteSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
    club_timezone: FromDishka[ZoneInfo],
) -> None:
    athlete_id = _context_int(await get_flow_context(state), "athlete_id")
    telegram_id = message.from_user.id if message.from_user is not None else None
    if athlete_id is None or telegram_id is None:
        return
    await _show_card(
        message=message,
        state=state,
        actor_telegram_id=telegram_id,
        athlete_id=athlete_id,
        interactor=interactor,
        renderer=renderer,
        club_timezone=club_timezone,
        mode=RenderMode.NEW,
    )


def create_subscription_correction_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_subscription_view,
        F.data == VIEW_SUBSCRIPTION_ACTION,
    )
    router.callback_query.register(
        handle_select_subscription_athlete,
        AthleteSelectorCallback.filter(
            (F.purpose == AthleteSelectionPurpose.SUBSCRIPTION_VIEW)
            & (F.action == AthleteSelectorAction.SELECT)
        ),
        AthleteSelectorStates.selecting,
    )
    router.callback_query.register(
        handle_begin_correction,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.BEGIN
        ),
        SubscriptionCorrectionStates.viewing,
    )
    router.callback_query.register(
        handle_edit_remaining_visits,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.EDIT_REMAINING
        ),
        SubscriptionCorrectionStates.editing,
    )
    router.callback_query.register(
        handle_edit_expires_at,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.EDIT_EXPIRES_AT
        ),
        SubscriptionCorrectionStates.editing,
    )
    router.callback_query.register(
        handle_edit_status,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.EDIT_STATUS
        ),
        SubscriptionCorrectionStates.editing,
    )
    router.callback_query.register(
        handle_set_status,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.SET_STATUS
        ),
        SubscriptionCorrectionStates.choosing_status,
    )
    router.callback_query.register(
        handle_review_correction,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.REVIEW
        ),
        SubscriptionCorrectionStates.editing,
    )
    router.callback_query.register(
        handle_confirm_correction,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.CONFIRM
        ),
        SubscriptionCorrectionStates.confirming,
    )
    router.callback_query.register(
        handle_back_to_view_athletes,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.SUBSCRIPTION_VIEW_ATHLETES)
        ),
        SubscriptionCorrectionStates.viewing,
    )
    router.callback_query.register(
        handle_back_to_draft,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.SUBSCRIPTION_CORRECTION_DRAFT)
        ),
        StateFilter(
            SubscriptionCorrectionStates.waiting_for_remaining_visits,
            SubscriptionCorrectionStates.waiting_for_expires_at,
            SubscriptionCorrectionStates.choosing_status,
            SubscriptionCorrectionStates.confirming,
        ),
    )
    router.callback_query.register(
        handle_return_to_card,
        NavigationCallback.filter(
            (F.target == NavigationTarget.SUBSCRIPTION_VIEW_CARD)
            & (
                (F.action == NavigationAction.CANCEL)
                | (F.action == NavigationAction.BACK)
            )
        ),
        StateFilter(SubscriptionCorrectionStates),
    )
    router.callback_query.register(
        handle_return_to_card,
        SubscriptionCorrectionCallback.filter(
            F.action == SubscriptionCorrectionAction.REOPEN
        ),
        SubscriptionCorrectionStates.viewing,
    )
    router.message.register(
        handle_cancel_correction_command,
        Command("cancel"),
        StateFilter(SubscriptionCorrectionStates),
    )
    router.message.register(
        handle_remaining_visits_input,
        SubscriptionCorrectionStates.waiting_for_remaining_visits,
    )
    router.message.register(
        handle_expires_at_input,
        SubscriptionCorrectionStates.waiting_for_expires_at,
    )
    return router


def parse_corrected_expires_at(
    value: str,
    *,
    original: datetime,
    club_timezone: ZoneInfo,
) -> datetime | None:
    if original.utcoffset() is None:
        return None
    normalized = value.strip()
    if _DATE_PATTERN.fullmatch(normalized) is None:
        return None
    try:
        corrected_date = datetime.strptime(normalized, "%d.%m.%Y").date()
    except ValueError:
        return None
    local_original = original.astimezone(club_timezone)
    local_corrected = datetime.combine(
        corrected_date,
        local_original.timetz(),
    )
    return local_corrected.astimezone(UTC)


async def _show_card(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    athlete_id: int,
    interactor: GetLatestAthleteSubscriptionInteractor,
    renderer: TelegramScreenRenderer,
    club_timezone: ZoneInfo,
    mode: RenderMode,
    notice: str | None = None,
) -> None:
    try:
        result = await _load_latest(
            actor_telegram_id=actor_telegram_id,
            athlete_id=athlete_id,
            interactor=interactor,
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
            mode=mode,
        )
        return
    except AthleteNotFoundError:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
            mode=mode,
        )
        return
    context: dict[str, object] = {"athlete_id": result.athlete_id}
    if result.latest is not None:
        context["subscription_id"] = result.latest.subscription_id
    await set_flow_context(state, context)
    await state.set_state(SubscriptionCorrectionStates.viewing)
    await _render(
        message,
        state,
        renderer,
        format_latest_subscription_card(
            result,
            club_timezone,
            notice=notice,
        ),
        _card_keyboard(has_subscription=result.latest is not None),
        mode=mode,
    )


async def _load_latest(
    *,
    actor_telegram_id: int,
    athlete_id: int,
    interactor: GetLatestAthleteSubscriptionInteractor,
) -> GetLatestAthleteSubscriptionResult:
    return await interactor(
        GetLatestAthleteSubscriptionQuery(
            actor_telegram_id=actor_telegram_id,
            athlete_id=athlete_id,
        )
    )


def _card_keyboard(*, has_subscription: bool) -> InlineKeyboardMarkup:
    rows: list[tuple[InlineKeyboardButton, ...]] = []
    if has_subscription:
        rows.append(
            (
                build_callback_button(
                    text="Внести корректировку",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.BEGIN,
                        value="0",
                    ).pack(),
                ),
            )
        )
    rows.extend(
        [
            (
                build_back_button(
                    NavigationTarget.SUBSCRIPTION_VIEW_ATHLETES
                ),
            ),
            (build_menu_button(),),
        ]
    )
    return build_inline_keyboard(*rows)


async def _set_draft_context(
    state: FSMContext,
    result: GetLatestAthleteSubscriptionResult,
) -> None:
    latest = result.latest
    if latest is None:
        raise RuntimeError("A correction draft requires a Subscription")
    await set_flow_context(
        state,
        {
            "athlete_id": result.athlete_id,
            "subscription_id": latest.subscription_id,
            "athlete_full_name": result.athlete_full_name,
            "is_unlimited": latest.is_unlimited,
            "original_remaining_visits": latest.remaining_visits,
            "original_expires_at": latest.expires_at.isoformat(),
            "original_status": latest.status.value,
            "remaining_visits_is_set": False,
        },
    )


async def _get_draft(state: FSMContext) -> CorrectionDraft | None:
    context = await get_flow_context(state)
    athlete_id = _context_int(context, "athlete_id")
    subscription_id = _context_int(context, "subscription_id")
    athlete_full_name = context.get("athlete_full_name")
    is_unlimited = context.get("is_unlimited")
    raw_original_expires_at = context.get("original_expires_at")
    raw_original_status = context.get("original_status")
    if (
        athlete_id is None
        or subscription_id is None
        or not isinstance(athlete_full_name, str)
        or not isinstance(is_unlimited, bool)
        or not isinstance(raw_original_expires_at, str)
        or not isinstance(raw_original_status, str)
    ):
        return None
    try:
        original_expires_at = datetime.fromisoformat(raw_original_expires_at)
        original_status = SubscriptionStatus(raw_original_status)
        expires_at = _optional_datetime(context.get("expires_at"))
        status = _optional_status(context.get("status"))
    except ValueError:
        return None
    original_remaining = context.get("original_remaining_visits")
    remaining = context.get("remaining_visits")
    if original_remaining is not None and not isinstance(original_remaining, int):
        return None
    if remaining is not None and not isinstance(remaining, int):
        return None
    return CorrectionDraft(
        athlete_id=athlete_id,
        subscription_id=subscription_id,
        athlete_full_name=athlete_full_name,
        is_unlimited=is_unlimited,
        original_remaining_visits=original_remaining,
        original_expires_at=original_expires_at,
        original_status=original_status,
        remaining_visits_is_set=context.get("remaining_visits_is_set") is True,
        remaining_visits=remaining,
        expires_at=expires_at,
        status=status,
    )


async def _show_draft(
    *,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    club_timezone: ZoneInfo,
    notice: str | None = None,
) -> None:
    draft = await _get_draft(state)
    if draft is None:
        return
    await state.set_state(SubscriptionCorrectionStates.editing)
    prefix = f"{notice}\n\n" if notice else ""
    remaining = (
        "Безлимит — не изменяется"
        if draft.is_unlimited
        else _format_change(
            str(draft.original_remaining_visits),
            str(draft.final_remaining_visits),
        )
    )
    expires_at = _format_change(
        _format_date(draft.original_expires_at, club_timezone),
        _format_date(draft.final_expires_at, club_timezone),
    )
    status = _format_change(
        format_subscription_status(draft.original_status),
        format_subscription_status(draft.final_status),
    )
    await _render(
        message,
        state,
        renderer,
        (
            f"{prefix}{TITLE}\n\n"
            f"Спортсмен:\n{draft.athlete_full_name}\n\n"
            f"Остаток посещений:\n{remaining}\n\n"
            f"Дата окончания:\n{expires_at}\n\n"
            f"Статус:\n{status}"
        ),
        _draft_keyboard(is_unlimited=draft.is_unlimited),
    )


def _draft_keyboard(*, is_unlimited: bool) -> InlineKeyboardMarkup:
    rows: list[tuple[InlineKeyboardButton, ...]] = []
    if not is_unlimited:
        rows.append(
            (
                build_callback_button(
                    text="Остаток посещений",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.EDIT_REMAINING,
                        value="0",
                    ).pack(),
                ),
            )
        )
    rows.extend(
        [
            (
                build_callback_button(
                    text="Дата окончания",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.EDIT_EXPIRES_AT,
                        value="0",
                    ).pack(),
                ),
                build_callback_button(
                    text="Статус",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.EDIT_STATUS,
                        value="0",
                    ).pack(),
                ),
            ),
            (
                build_callback_button(
                    text="Сохранить",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.REVIEW,
                        value="0",
                    ).pack(),
                ),
            ),
            (
                build_cancel_button(NavigationTarget.SUBSCRIPTION_VIEW_CARD),
            ),
        ]
    )
    return build_inline_keyboard(*rows)


def _prompt_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_back_button(NavigationTarget.SUBSCRIPTION_CORRECTION_DRAFT),
            build_cancel_button(NavigationTarget.SUBSCRIPTION_VIEW_CARD),
        )
    )


def _draft_changes(
    draft: CorrectionDraft,
    club_timezone: ZoneInfo,
) -> tuple[str, ...]:
    changes = []
    if draft.final_remaining_visits != draft.original_remaining_visits:
        changes.append(
            "Остаток:\n"
            f"{draft.original_remaining_visits} → {draft.final_remaining_visits}"
        )
    if draft.final_expires_at != draft.original_expires_at:
        changes.append(
            "Дата окончания:\n"
            f"{_format_date(draft.original_expires_at, club_timezone)} → "
            f"{_format_date(draft.final_expires_at, club_timezone)}"
        )
    if draft.final_status is not draft.original_status:
        changes.append(
            "Статус:\n"
            f"{format_subscription_status(draft.original_status)} → "
            f"{format_subscription_status(draft.final_status)}"
        )
    return tuple(changes)


async def _render_reopen_screen(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> None:
    await state.set_state(SubscriptionCorrectionStates.viewing)
    await _render(
        message,
        state,
        renderer,
        STALE_SUBSCRIPTION_TEXT,
        build_inline_keyboard(
            (
                build_callback_button(
                    text="Открыть данные заново",
                    callback_data=SubscriptionCorrectionCallback(
                        action=SubscriptionCorrectionAction.REOPEN,
                        value="0",
                    ).pack(),
                ),
            ),
            (
                build_back_button(
                    NavigationTarget.SUBSCRIPTION_VIEW_ATHLETES
                ),
                build_menu_button(),
            ),
        ),
    )


async def _show_terminal_error(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    *,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    await clear_flow_context(state)
    await _render(
        message,
        state,
        renderer,
        text,
        build_inline_keyboard((build_menu_button(),)),
        mode=mode,
    )


async def _render(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(text=text, reply_markup=reply_markup),
        mode=mode,
        editable_message=message,
    )


def _format_change(before: str, after: str) -> str:
    return before if before == after else f"{before} → {after}"


def _format_date(value: datetime, club_timezone: ZoneInfo) -> str:
    return value.astimezone(club_timezone).strftime("%d.%m.%Y")


def _parse_positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _context_int(context: dict[str, object], key: str) -> int | None:
    value = context.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return datetime.fromisoformat(value)


def _optional_status(value: object) -> SubscriptionStatus | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    return SubscriptionStatus(value)
