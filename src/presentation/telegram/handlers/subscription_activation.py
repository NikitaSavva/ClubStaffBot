from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.athletes import (
    AthleteSummary,
    ListAthletesInteractor,
    ListAthletesQuery,
)
from application.club import (
    ListTrainingGroupsInteractor,
    ListTrainingGroupsQuery,
    TrainingGroupSummary,
)
from application.club.errors import TrainingGroupNotFoundError
from application.identity import GetUserMenuContextInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthleteNotFoundError,
    UserNotFoundError,
)
from application.subscriptions import (
    ActivateSubscriptionCommand,
    ActivateSubscriptionInteractor,
    ActivateSubscriptionResult,
    ListActiveSubscriptionPlansInteractor,
    ListActiveSubscriptionPlansQuery,
    SubscriptionPlanSummary,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    SubscriptionGroupForbiddenError,
    SubscriptionGroupRequiredError,
    SubscriptionPlanInactiveError,
    SubscriptionPlanNotApplicableToGroupError,
    SubscriptionPlanNotFoundError,
)
from domain.subscriptions import SubscriptionAccessScope
from presentation.telegram.handlers.menu import (
    set_administrative_navigation_context,
    show_active_role_panel,
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
    build_cancel_button,
    build_menu_button,
)
from presentation.telegram.presenters.athletes import format_athlete_label
from presentation.telegram.presenters.training_groups import (
    format_training_group_details,
    format_training_group_label,
)
from presentation.telegram.screen import (
    BannerContext,
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import SubscriptionActivationStates
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
)

ACTIVATE_SUBSCRIPTION_ACTION = "administrator.activate_subscription"
SELECT_ATHLETE_PREFIX = "subscription:athlete:"
SELECT_PLAN_PREFIX = "subscription:plan:"
SELECT_GROUP_PREFIX = "subscription:group:"
CONFIRM_ACTIVATION_ACTION = "subscription:activate"

TITLE = "Выдача абонемента"
PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
ATHLETE_UNAVAILABLE_TEXT = "Выбранный спортсмен больше не доступен."
PLAN_UNAVAILABLE_TEXT = "Выбранный тариф больше не доступен."
GROUP_UNAVAILABLE_TEXT = "Выбранная группа больше не доступна для тарифа."
ACTIVE_SUBSCRIPTION_TEXT = (
    "У спортсмена уже есть действующий абонемент. Замена активного "
    "абонемента не входит в MVP."
)
ACTIVATION_CANCELLED_TEXT = "Выдача абонемента отменена."


def build_athlete_selection_keyboard(
    athletes: tuple[AthleteSummary, ...],
) -> InlineKeyboardMarkup:
    rows = tuple(
        (
            build_callback_button(
                text=format_athlete_label(athlete),
                callback_data=(
                    f"{SELECT_ATHLETE_PREFIX}{athlete.athlete_id}"
                ),
            ),
        )
        for athlete in athletes
    )
    return build_inline_keyboard(*rows, (build_cancel_button(),))


def build_plan_selection_keyboard(
    plans: tuple[SubscriptionPlanSummary, ...],
) -> InlineKeyboardMarkup:
    rows = tuple(
        (
            build_callback_button(
                text=format_subscription_plan_label(plan),
                callback_data=(
                    f"{SELECT_PLAN_PREFIX}{plan.subscription_plan_id}"
                ),
            ),
        )
        for plan in plans
    )
    return build_inline_keyboard(
        *rows,
        (
            build_back_button(NavigationTarget.SUBSCRIPTION_ATHLETES),
            build_cancel_button(),
        ),
    )


def build_group_selection_keyboard(
    groups: tuple[TrainingGroupSummary, ...],
) -> InlineKeyboardMarkup:
    rows = tuple(
        (
            build_callback_button(
                text=format_training_group_label(group),
                callback_data=(
                    f"{SELECT_GROUP_PREFIX}{group.training_group_id}"
                ),
            ),
        )
        for group in groups
    )
    return build_inline_keyboard(
        *rows,
        (
            build_back_button(NavigationTarget.SUBSCRIPTION_PLANS),
            build_cancel_button(),
        ),
    )


def build_activation_confirmation_keyboard(
    plan: SubscriptionPlanSummary,
) -> InlineKeyboardMarkup:
    back_target = (
        NavigationTarget.SUBSCRIPTION_GROUPS
        if plan.access_scope is SubscriptionAccessScope.SPECIFIC_GROUP
        else NavigationTarget.SUBSCRIPTION_PLANS
    )
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Активировать",
                callback_data=CONFIRM_ACTIVATION_ACTION,
            ),
        ),
        (build_back_button(back_target), build_cancel_button()),
    )


def format_subscription_plan_label(plan: SubscriptionPlanSummary) -> str:
    price = f"{plan.price:,.0f}".replace(",", " ")
    return f"{plan.name} — {price} ₽"


@inject
async def handle_begin_subscription_activation(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await set_administrative_navigation_context(state)
    await set_flow_context(state, {})
    await _show_athletes(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        interactor=athletes_interactor,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_select_subscription_athlete(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    plans_interactor: FromDishka[ListActiveSubscriptionPlansInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    athlete_id = _parse_id(callback.data, SELECT_ATHLETE_PREFIX)
    if not isinstance(message, Message) or athlete_id is None:
        return
    athletes = await _load_athletes(
        callback.from_user.id,
        athletes_interactor,
        message,
        state,
        renderer,
    )
    if athletes is None:
        return
    athlete = _find_athlete(athletes, athlete_id)
    if athlete is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return
    await set_flow_context(state, {"athlete_id": athlete_id})
    await _show_plans(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete=athlete,
        interactor=plans_interactor,
        renderer=renderer,
    )


@inject
async def handle_select_subscription_plan(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    plans_interactor: FromDishka[ListActiveSubscriptionPlansInteractor],
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    plan_id = _parse_id(callback.data, SELECT_PLAN_PREFIX)
    if not isinstance(message, Message) or plan_id is None:
        return
    base = await _load_athlete_and_plan(
        callback.from_user.id,
        state,
        athletes_interactor,
        plans_interactor,
        message,
        renderer,
        selected_plan_id=plan_id,
    )
    if base is None:
        return
    athlete, plan = base
    await set_flow_context(
        state,
        {"athlete_id": athlete.athlete_id, "plan_id": plan_id},
    )
    if plan.access_scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS:
        await _show_confirmation(
            message,
            state,
            athlete,
            plan,
            None,
            renderer,
        )
        return
    await _show_groups(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete=athlete,
        plan=plan,
        interactor=groups_interactor,
        renderer=renderer,
    )


@inject
async def handle_select_subscription_group(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    plans_interactor: FromDishka[ListActiveSubscriptionPlansInteractor],
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    group_id = _parse_id(callback.data, SELECT_GROUP_PREFIX)
    if not isinstance(message, Message) or group_id is None:
        return
    context = await _load_confirmation_context(
        callback.from_user.id,
        state,
        athletes_interactor,
        plans_interactor,
        groups_interactor,
        message,
        renderer,
        selected_group_id=group_id,
    )
    if context is None:
        return
    athlete, plan, group = context
    if group is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            GROUP_UNAVAILABLE_TEXT,
        )
        return
    await set_flow_context(
        state,
        {
            "athlete_id": athlete.athlete_id,
            "plan_id": plan.subscription_plan_id,
            "group_id": group.training_group_id,
        },
    )
    await _show_confirmation(
        message,
        state,
        athlete,
        plan,
        group,
        renderer,
    )


@inject
async def handle_confirm_subscription_activation(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    activate_interactor: FromDishka[ActivateSubscriptionInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    flow_context = await get_flow_context(state)
    athlete_id = _flow_id(flow_context, "athlete_id")
    plan_id = _flow_id(flow_context, "plan_id")
    group_id = _flow_id(flow_context, "group_id")
    if athlete_id is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return
    if plan_id is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            PLAN_UNAVAILABLE_TEXT,
        )
        return
    try:
        result = await activate_interactor(
            ActivateSubscriptionCommand(
                actor_telegram_id=callback.from_user.id,
                athlete_id=athlete_id,
                subscription_plan_id=plan_id,
                training_group_id=group_id,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
        )
        return
    except AthleteNotFoundError:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return
    except (SubscriptionPlanNotFoundError, SubscriptionPlanInactiveError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PLAN_UNAVAILABLE_TEXT,
        )
        return
    except (
        TrainingGroupNotFoundError,
        SubscriptionGroupForbiddenError,
        SubscriptionGroupRequiredError,
        SubscriptionPlanNotApplicableToGroupError,
    ):
        await _show_terminal_error(
            message,
            state,
            renderer,
            GROUP_UNAVAILABLE_TEXT,
        )
        return
    except ActiveSubscriptionAlreadyExistsError:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ACTIVE_SUBSCRIPTION_TEXT,
        )
        return

    group: TrainingGroupSummary | None = None
    if result.training_group_id is not None:
        try:
            groups = await groups_interactor(
                ListTrainingGroupsQuery(
                    actor_telegram_id=callback.from_user.id
                )
            )
        except (AdministratorPermissionRequiredError, UserNotFoundError):
            groups = ()
        group = _find_group(groups, result.training_group_id)
    await clear_flow_context(state)
    await _render_result(
        message,
        state,
        renderer,
        _success_text(result, group),
    )


@inject
async def handle_back_to_subscription_athletes(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await set_flow_context(state, {})
    await _show_athletes(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        interactor=athletes_interactor,
        renderer=renderer,
    )


@inject
async def handle_back_to_subscription_plans(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    plans_interactor: FromDishka[ListActiveSubscriptionPlansInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    athlete = await _load_selected_athlete(
        callback.from_user.id,
        state,
        athletes_interactor,
        message,
        renderer,
    )
    if athlete is None:
        return
    await set_flow_context(state, {"athlete_id": athlete.athlete_id})
    await _show_plans(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete=athlete,
        interactor=plans_interactor,
        renderer=renderer,
    )


@inject
async def handle_back_to_subscription_groups(
    callback: CallbackQuery,
    state: FSMContext,
    athletes_interactor: FromDishka[ListAthletesInteractor],
    plans_interactor: FromDishka[ListActiveSubscriptionPlansInteractor],
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    base = await _load_athlete_and_plan(
        callback.from_user.id,
        state,
        athletes_interactor,
        plans_interactor,
        message,
        renderer,
    )
    if base is None:
        return
    athlete, plan = base
    await set_flow_context(
        state,
        {
            "athlete_id": athlete.athlete_id,
            "plan_id": plan.subscription_plan_id,
        },
    )
    await _show_groups(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        athlete=athlete,
        plan=plan,
        interactor=groups_interactor,
        renderer=renderer,
    )


@inject
async def handle_cancel_subscription_activation_callback(
    callback: CallbackQuery,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await _cancel_activation(
        message,
        state,
        callback.from_user.id,
        menu_interactor,
        renderer,
    )


@inject
async def handle_cancel_subscription_activation_command(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_id = message.from_user.id if message.from_user is not None else None
    await _cancel_activation(
        message,
        state,
        telegram_id,
        menu_interactor,
        renderer,
    )


def create_subscription_activation_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_subscription_activation,
        F.data == ACTIVATE_SUBSCRIPTION_ACTION,
    )
    router.message.register(
        handle_cancel_subscription_activation_command,
        Command("cancel"),
        StateFilter(SubscriptionActivationStates),
    )
    router.callback_query.register(
        handle_cancel_subscription_activation_callback,
        NavigationCallback.filter(
            (F.action == NavigationAction.CANCEL)
            & (F.target == NavigationTarget.ROLE_PANEL)
        ),
        StateFilter(SubscriptionActivationStates),
    )
    router.callback_query.register(
        handle_select_subscription_athlete,
        F.data.startswith(SELECT_ATHLETE_PREFIX),
        SubscriptionActivationStates.selecting_athlete,
    )
    router.callback_query.register(
        handle_back_to_subscription_athletes,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.SUBSCRIPTION_ATHLETES)
        ),
        SubscriptionActivationStates.selecting_plan,
    )
    router.callback_query.register(
        handle_select_subscription_plan,
        F.data.startswith(SELECT_PLAN_PREFIX),
        SubscriptionActivationStates.selecting_plan,
    )
    router.callback_query.register(
        handle_back_to_subscription_plans,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.SUBSCRIPTION_PLANS)
        ),
        StateFilter(
            SubscriptionActivationStates.selecting_group,
            SubscriptionActivationStates.confirming,
        ),
    )
    router.callback_query.register(
        handle_select_subscription_group,
        F.data.startswith(SELECT_GROUP_PREFIX),
        SubscriptionActivationStates.selecting_group,
    )
    router.callback_query.register(
        handle_back_to_subscription_groups,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.SUBSCRIPTION_GROUPS)
        ),
        SubscriptionActivationStates.confirming,
    )
    router.callback_query.register(
        handle_confirm_subscription_activation,
        F.data == CONFIRM_ACTIVATION_ACTION,
        SubscriptionActivationStates.confirming,
    )
    return router


async def _show_athletes(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    interactor: ListAthletesInteractor,
    renderer: TelegramScreenRenderer,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    athletes = await _load_athletes(
        actor_telegram_id,
        interactor,
        message,
        state,
        renderer,
        mode=mode,
    )
    if athletes is None:
        return
    await state.set_state(SubscriptionActivationStates.selecting_athlete)
    text = (
        f"{TITLE}\n\nВыберите спортсмена:"
        if athletes
        else f"{TITLE}\n\nСпортсмены не найдены."
    )
    await _render_flow(
        message,
        state,
        renderer,
        text,
        build_athlete_selection_keyboard(athletes),
        mode=mode,
    )


async def _show_plans(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    athlete: AthleteSummary,
    interactor: ListActiveSubscriptionPlansInteractor,
    renderer: TelegramScreenRenderer,
) -> None:
    plans = await _load_plans(
        actor_telegram_id,
        interactor,
        message,
        state,
        renderer,
    )
    if plans is None:
        return
    await state.set_state(SubscriptionActivationStates.selecting_plan)
    text = (
        f"{TITLE}\n\nСпортсмен:\n{athlete.full_name}\n\nВыберите тариф:"
        if plans
        else (
            f"{TITLE}\n\nСпортсмен:\n{athlete.full_name}\n\n"
            "Активные тарифы не найдены."
        )
    )
    await _render_flow(
        message,
        state,
        renderer,
        text,
        build_plan_selection_keyboard(plans),
    )


async def _show_groups(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    athlete: AthleteSummary,
    plan: SubscriptionPlanSummary,
    interactor: ListTrainingGroupsInteractor,
    renderer: TelegramScreenRenderer,
) -> None:
    groups = await _load_groups(
        actor_telegram_id,
        interactor,
        message,
        state,
        renderer,
    )
    if groups is None:
        return
    applicable = _applicable_groups(groups, plan)
    await state.set_state(SubscriptionActivationStates.selecting_group)
    text = (
        f"{TITLE}\n\nСпортсмен:\n{athlete.full_name}\n\n"
        f"Тариф:\n{format_subscription_plan_label(plan)}\n\n"
        "Выберите группу:"
        if applicable
        else (
            f"{TITLE}\n\nСпортсмен:\n{athlete.full_name}\n\n"
            f"Тариф:\n{format_subscription_plan_label(plan)}\n\n"
            "Подходящие группы не найдены."
        )
    )
    await _render_flow(
        message,
        state,
        renderer,
        text,
        build_group_selection_keyboard(applicable),
    )


async def _show_confirmation(
    message: Message,
    state: FSMContext,
    athlete: AthleteSummary,
    plan: SubscriptionPlanSummary,
    group: TrainingGroupSummary | None,
    renderer: TelegramScreenRenderer,
) -> None:
    await state.set_state(SubscriptionActivationStates.confirming)
    await _render_flow(
        message,
        state,
        renderer,
        _confirmation_text(athlete, plan, group),
        build_activation_confirmation_keyboard(plan),
    )


async def _load_athletes(
    actor_telegram_id: int,
    interactor: ListAthletesInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    *,
    mode: RenderMode = RenderMode.EDIT,
) -> tuple[AthleteSummary, ...] | None:
    try:
        return await interactor(
            ListAthletesQuery(actor_telegram_id=actor_telegram_id)
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
            mode=mode,
        )
        return None


async def _load_plans(
    actor_telegram_id: int,
    interactor: ListActiveSubscriptionPlansInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> tuple[SubscriptionPlanSummary, ...] | None:
    try:
        return await interactor(
            ListActiveSubscriptionPlansQuery(
                actor_telegram_id=actor_telegram_id
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
        )
        return None


async def _load_groups(
    actor_telegram_id: int,
    interactor: ListTrainingGroupsInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> tuple[TrainingGroupSummary, ...] | None:
    try:
        return await interactor(
            ListTrainingGroupsQuery(actor_telegram_id=actor_telegram_id)
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_terminal_error(
            message,
            state,
            renderer,
            PERMISSION_DENIED_TEXT,
        )
        return None


async def _load_selected_athlete(
    actor_telegram_id: int,
    state: FSMContext,
    interactor: ListAthletesInteractor,
    message: Message,
    renderer: TelegramScreenRenderer,
) -> AthleteSummary | None:
    athlete_id = _flow_id(await get_flow_context(state), "athlete_id")
    if athlete_id is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
        return None
    athletes = await _load_athletes(
        actor_telegram_id,
        interactor,
        message,
        state,
        renderer,
    )
    if athletes is None:
        return None
    athlete = _find_athlete(athletes, athlete_id)
    if athlete is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            ATHLETE_UNAVAILABLE_TEXT,
        )
    return athlete


async def _load_athlete_and_plan(
    actor_telegram_id: int,
    state: FSMContext,
    athletes_interactor: ListAthletesInteractor,
    plans_interactor: ListActiveSubscriptionPlansInteractor,
    message: Message,
    renderer: TelegramScreenRenderer,
    *,
    selected_plan_id: int | None = None,
) -> tuple[AthleteSummary, SubscriptionPlanSummary] | None:
    athlete = await _load_selected_athlete(
        actor_telegram_id,
        state,
        athletes_interactor,
        message,
        renderer,
    )
    if athlete is None:
        return None
    flow = await get_flow_context(state)
    plan_id = selected_plan_id or _flow_id(flow, "plan_id")
    plans = await _load_plans(
        actor_telegram_id,
        plans_interactor,
        message,
        state,
        renderer,
    )
    if plans is None:
        return None
    plan = _find_plan(plans, plan_id)
    if plan is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            PLAN_UNAVAILABLE_TEXT,
        )
        return None
    return athlete, plan


async def _load_confirmation_context(
    actor_telegram_id: int,
    state: FSMContext,
    athletes_interactor: ListAthletesInteractor,
    plans_interactor: ListActiveSubscriptionPlansInteractor,
    groups_interactor: ListTrainingGroupsInteractor,
    message: Message,
    renderer: TelegramScreenRenderer,
    *,
    selected_group_id: int | None = None,
) -> tuple[
    AthleteSummary,
    SubscriptionPlanSummary,
    TrainingGroupSummary | None,
] | None:
    base = await _load_athlete_and_plan(
        actor_telegram_id,
        state,
        athletes_interactor,
        plans_interactor,
        message,
        renderer,
    )
    if base is None:
        return None
    athlete, plan = base
    if plan.access_scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS:
        return athlete, plan, None
    flow = await get_flow_context(state)
    group_id = selected_group_id or _flow_id(flow, "group_id")
    groups = await _load_groups(
        actor_telegram_id,
        groups_interactor,
        message,
        state,
        renderer,
    )
    if groups is None:
        return None
    group = _find_group(_applicable_groups(groups, plan), group_id)
    if group is None:
        await _show_terminal_error(
            message,
            state,
            renderer,
            GROUP_UNAVAILABLE_TEXT,
        )
        return None
    return athlete, plan, group


async def _show_terminal_error(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    *,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    await clear_flow_context(state)
    await _render_flow(
        message,
        state,
        renderer,
        text,
        build_inline_keyboard((build_menu_button(),)),
        mode=mode,
    )


async def _cancel_activation(
    message: Message,
    state: FSMContext,
    telegram_id: int | None,
    menu_interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
) -> None:
    await clear_flow_context(state)
    if telegram_id is None:
        await _render_flow(
            message,
            state,
            renderer,
            ACTIVATION_CANCELLED_TEXT,
            None,
            mode=RenderMode.NEW,
        )
        return
    await show_active_role_panel(
        chat_id=message.chat.id,
        telegram_id=telegram_id,
        state=state,
        interactor=menu_interactor,
        renderer=renderer,
        editable_message=message,
        notice=ACTIVATION_CANCELLED_TEXT,
        mode=RenderMode.NEW,
    )


async def _render_flow(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
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


async def _render_result(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
) -> None:
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=text,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
            banner=BannerContext.ADMIN_PANEL,
        ),
        mode=RenderMode.NEW,
        editable_message=message,
    )


def _confirmation_text(
    athlete: AthleteSummary,
    plan: SubscriptionPlanSummary,
    group: TrainingGroupSummary | None,
) -> str:
    visits = (
        "Без ограничений"
        if plan.visit_limit is None
        else str(plan.visit_limit)
    )
    access = (
        f"Группа:\n{format_training_group_details(group)}"
        if group is not None
        else "Доступ:\nВсе обычные группы клуба\n\nМини-группы:\nНе входят"
    )
    return (
        "Выдать абонемент?\n\n"
        f"Спортсмен:\n{athlete.full_name}\n\n"
        f"Тариф:\n{format_subscription_plan_label(plan)}\n\n"
        f"{access}\n\n"
        f"Срок:\n{_format_duration(plan.duration_months)}\n\n"
        f"Посещений:\n{visits}"
    )


def _success_text(
    result: ActivateSubscriptionResult,
    group: TrainingGroupSummary | None,
) -> str:
    if group is not None:
        access = f"Группа:\n{format_training_group_details(group)}"
    elif result.training_group_id is not None:
        access = "Группа:\nДанные группы недоступны"
    else:
        access = "Доступ:\nВсе обычные группы клуба"
    remaining = (
        "Без ограничений"
        if result.remaining_visits is None
        else str(result.remaining_visits)
    )
    return (
        "Абонемент активирован\n\n"
        f"Спортсмен:\n{result.athlete_full_name}\n\n"
        f"Тариф:\n{result.plan_name}\n\n"
        f"{access}\n\n"
        f"Действует:\n{result.starts_at:%d.%m.%Y} – "
        f"{result.expires_at:%d.%m.%Y}\n\n"
        f"Осталось посещений:\n{remaining}"
    )


def _format_duration(duration_months: int) -> str:
    tail = duration_months % 100
    if 11 <= tail <= 14:
        word = "месяцев"
    elif duration_months % 10 == 1:
        word = "месяц"
    elif duration_months % 10 in (2, 3, 4):
        word = "месяца"
    else:
        word = "месяцев"
    return f"{duration_months} {word}"


def _applicable_groups(
    groups: tuple[TrainingGroupSummary, ...],
    plan: SubscriptionPlanSummary,
) -> tuple[TrainingGroupSummary, ...]:
    if plan.required_group_type is None:
        return groups
    return tuple(
        group
        for group in groups
        if group.group_type is plan.required_group_type
    )


def _find_athlete(
    athletes: tuple[AthleteSummary, ...],
    athlete_id: int,
) -> AthleteSummary | None:
    return next(
        (athlete for athlete in athletes if athlete.athlete_id == athlete_id),
        None,
    )


def _find_plan(
    plans: tuple[SubscriptionPlanSummary, ...],
    plan_id: int | None,
) -> SubscriptionPlanSummary | None:
    return next(
        (
            plan
            for plan in plans
            if plan.subscription_plan_id == plan_id
        ),
        None,
    )


def _find_group(
    groups: tuple[TrainingGroupSummary, ...],
    group_id: int | None,
) -> TrainingGroupSummary | None:
    return next(
        (group for group in groups if group.training_group_id == group_id),
        None,
    )


def _parse_id(data: str | None, prefix: str) -> int | None:
    if data is None or not data.startswith(prefix):
        return None
    try:
        return int(data.removeprefix(prefix))
    except ValueError:
        return None


def _flow_id(flow_context: dict[str, object], key: str) -> int | None:
    value = flow_context.get(key)
    return value if isinstance(value, int) else None
