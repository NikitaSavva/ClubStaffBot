from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.club import (
    AssignTrainingGroupTrainerCommand,
    AssignTrainingGroupTrainerInteractor,
    ListTrainerCandidatesInteractor,
    ListTrainerCandidatesQuery,
    ListTrainingGroupsInteractor,
    ListTrainingGroupsQuery,
    TrainingGroupSummary,
)
from application.club.errors import (
    TargetUserIsNotTrainerError,
    TrainingGroupNotFoundError,
    TrainingGroupTrainerAlreadyAssignedError,
)
from application.identity import BotUserSummary, GetUserMenuContextInteractor
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    UserNotFoundError,
)
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
from presentation.telegram.presenters.training_groups import (
    format_training_group_button_label,
    format_training_group_details,
    format_training_group_selection_details,
)
from presentation.telegram.screen import (
    BannerContext,
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import TrainerAssignmentStates
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
)

ASSIGN_TRAINER_ACTION = "administrator.assign_trainer"
SELECT_GROUP_PREFIX = "group_trainer:group:"
SELECT_TRAINER_PREFIX = "group_trainer:user:"
CONFIRM_ASSIGN_TRAINER_ACTION = "group_trainer:confirm"

TITLE = "Назначение тренера"
SELECT_GROUP_TEXT = f"{TITLE}\n\nВыберите группу:"
NO_GROUPS_TEXT = f"{TITLE}\n\nТренировочные группы не найдены."
NO_TRAINERS_BODY = "В системе пока нет пользователей с ролью «Тренер»."
PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
GROUP_UNAVAILABLE_TEXT = "Выбранная группа больше не доступна."
TRAINER_UNAVAILABLE_TEXT = (
    "Выбранный пользователь больше не доступен как тренер."
)
ASSIGNMENT_CANCELLED_TEXT = "Назначение тренера отменено."


def build_group_selection_keyboard(
    groups: tuple[TrainingGroupSummary, ...],
) -> InlineKeyboardMarkup:
    rows = tuple(
        (
            build_callback_button(
                text=(
                    f"✓ {format_training_group_button_label(group)}"
                    if group.trainer is not None
                    else format_training_group_button_label(group)
                ),
                callback_data=(
                    f"{SELECT_GROUP_PREFIX}{group.training_group_id}"
                ),
            ),
        )
        for group in groups
    )
    return build_inline_keyboard(*rows, (build_cancel_button(),))


def build_trainer_selection_keyboard(
    trainers: tuple[BotUserSummary, ...],
) -> InlineKeyboardMarkup:
    rows = tuple(
        (
            build_callback_button(
                text=trainer.display_name,
                callback_data=f"{SELECT_TRAINER_PREFIX}{trainer.user_id}",
            ),
        )
        for trainer in trainers
    )
    return build_inline_keyboard(
        *rows,
        (
            build_back_button(NavigationTarget.TRAINING_GROUPS),
            build_cancel_button(),
        ),
    )


def build_confirmation_keyboard() -> InlineKeyboardMarkup:
    return build_inline_keyboard(
        (
            build_callback_button(
                text="Назначить",
                callback_data=CONFIRM_ASSIGN_TRAINER_ACTION,
            ),
        ),
        (
            build_back_button(NavigationTarget.TRAINER_CANDIDATES),
            build_cancel_button(),
        ),
    )


def build_trainer_selection_screen(
    group: TrainingGroupSummary,
    trainers: tuple[BotUserSummary, ...],
) -> TelegramScreen:
    text = (
        f"{TITLE}\n\nГруппа:\n{format_training_group_details(group)}\n\n"
        "Выберите тренера:"
        if trainers
        else (
            f"{TITLE}\n\nГруппа:\n"
            f"{format_training_group_details(group)}\n\n"
            f"{NO_TRAINERS_BODY}"
        )
    )
    return TelegramScreen(
        text=text,
        reply_markup=build_trainer_selection_keyboard(trainers),
        banner=BannerContext.ADMIN_PANEL,
    )


@inject
async def handle_begin_trainer_assignment(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await set_administrative_navigation_context(state)
    await set_flow_context(state, {})
    await _show_groups(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        groups_interactor=groups_interactor,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_select_training_group(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    trainers_interactor: FromDishka[ListTrainerCandidatesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return
    training_group_id = _parse_id(callback.data, SELECT_GROUP_PREFIX)
    if training_group_id is None:
        await _show_group_unavailable(message, state, renderer)
        return

    groups = await _load_groups(
        actor_telegram_id=callback.from_user.id,
        groups_interactor=groups_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if groups is None:
        return
    group = _find_group(groups, training_group_id)
    if group is None:
        await _show_group_unavailable(message, state, renderer)
        return

    await set_flow_context(
        state,
        {"training_group_id": training_group_id},
    )
    if group.trainer is not None:
        await _show_assigned_group(message, state, group, renderer)
        return

    trainers = await _load_trainers(
        actor_telegram_id=callback.from_user.id,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if trainers is None:
        return
    await _show_trainers(message, state, group, trainers, renderer)


@inject
async def handle_select_trainer(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    trainers_interactor: FromDishka[ListTrainerCandidatesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return
    trainer_user_id = _parse_id(callback.data, SELECT_TRAINER_PREFIX)
    training_group_id = _flow_id(await get_flow_context(state), "training_group_id")
    if trainer_user_id is None or training_group_id is None:
        await _show_trainer_unavailable(message, state, renderer)
        return

    context = await _load_selection_context(
        actor_telegram_id=callback.from_user.id,
        training_group_id=training_group_id,
        trainer_user_id=trainer_user_id,
        groups_interactor=groups_interactor,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if context is None:
        return
    group, trainer = context
    if group.trainer is not None:
        await _show_assigned_group(message, state, group, renderer)
        return

    await set_flow_context(
        state,
        {
            "training_group_id": training_group_id,
            "trainer_user_id": trainer_user_id,
        },
    )
    await state.set_state(TrainerAssignmentStates.confirming)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=_confirmation_text(group, trainer),
        reply_markup=build_confirmation_keyboard(),
    )


@inject
async def handle_confirm_trainer_assignment(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    trainers_interactor: FromDishka[ListTrainerCandidatesInteractor],
    assign_interactor: FromDishka[AssignTrainingGroupTrainerInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    flow_context = await get_flow_context(state)
    training_group_id = _flow_id(flow_context, "training_group_id")
    trainer_user_id = _flow_id(flow_context, "trainer_user_id")
    if training_group_id is None or trainer_user_id is None:
        await _show_trainer_unavailable(message, state, renderer)
        return

    try:
        await assign_interactor(
            AssignTrainingGroupTrainerCommand(
                actor_telegram_id=callback.from_user.id,
                training_group_id=training_group_id,
                trainer_user_id=trainer_user_id,
            )
        )
    except AdministratorPermissionRequiredError:
        await _show_permission_denied(message, state, renderer)
        return
    except UserNotFoundError:
        await _show_trainer_unavailable(message, state, renderer)
        return
    except TrainingGroupNotFoundError:
        await _show_group_unavailable(message, state, renderer)
        return
    except TargetUserIsNotTrainerError:
        await _show_trainer_unavailable(message, state, renderer)
        return
    except TrainingGroupTrainerAlreadyAssignedError:
        groups = await _load_groups(
            actor_telegram_id=callback.from_user.id,
            groups_interactor=groups_interactor,
            message=message,
            state=state,
            renderer=renderer,
        )
        if groups is None:
            return
        current_group = _find_group(groups, training_group_id)
        if current_group is None:
            await _show_group_unavailable(message, state, renderer)
        else:
            await _show_assigned_group(
                message,
                state,
                current_group,
                renderer,
            )
        return

    context = await _load_selection_context(
        actor_telegram_id=callback.from_user.id,
        training_group_id=training_group_id,
        trainer_user_id=trainer_user_id,
        groups_interactor=groups_interactor,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if context is None:
        await clear_flow_context(state)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text="Тренер назначен.",
            reply_markup=build_inline_keyboard((build_menu_button(),)),
        )
        return
    group, trainer = context
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=_success_text(group, trainer),
        reply_markup=build_inline_keyboard((build_menu_button(),)),
    )


@inject
async def handle_back_to_training_groups(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await set_flow_context(state, {})
    await _show_groups(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        groups_interactor=groups_interactor,
        renderer=renderer,
        mode=RenderMode.EDIT,
    )


@inject
async def handle_back_to_trainer_candidates(
    callback: CallbackQuery,
    state: FSMContext,
    groups_interactor: FromDishka[ListTrainingGroupsInteractor],
    trainers_interactor: FromDishka[ListTrainerCandidatesInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    training_group_id = _flow_id(
        await get_flow_context(state),
        "training_group_id",
    )
    if training_group_id is None:
        await _show_group_unavailable(message, state, renderer)
        return
    context = await _load_group_and_trainers(
        actor_telegram_id=callback.from_user.id,
        training_group_id=training_group_id,
        groups_interactor=groups_interactor,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if context is None:
        return
    group, trainers = context
    if group.trainer is not None:
        await _show_assigned_group(message, state, group, renderer)
        return
    await set_flow_context(
        state,
        {"training_group_id": training_group_id},
    )
    await _show_trainers(message, state, group, trainers, renderer)


@inject
async def handle_cancel_trainer_assignment_callback(
    callback: CallbackQuery,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await _cancel_assignment(
        message=message,
        state=state,
        telegram_id=callback.from_user.id,
        menu_interactor=menu_interactor,
        renderer=renderer,
    )


@inject
async def handle_cancel_trainer_assignment_command(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await _cancel_assignment(
        message=message,
        state=state,
        telegram_id=(
            message.from_user.id if message.from_user is not None else None
        ),
        menu_interactor=menu_interactor,
        renderer=renderer,
    )


def create_trainer_assignment_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_trainer_assignment,
        F.data == ASSIGN_TRAINER_ACTION,
    )
    router.message.register(
        handle_cancel_trainer_assignment_command,
        Command("cancel"),
        StateFilter(TrainerAssignmentStates),
    )
    router.callback_query.register(
        handle_cancel_trainer_assignment_callback,
        NavigationCallback.filter(
            (F.action == NavigationAction.CANCEL)
            & (F.target == NavigationTarget.ROLE_PANEL)
        ),
        StateFilter(TrainerAssignmentStates),
    )
    router.callback_query.register(
        handle_select_training_group,
        F.data.startswith(SELECT_GROUP_PREFIX),
        TrainerAssignmentStates.selecting_group,
    )
    router.callback_query.register(
        handle_back_to_training_groups,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.TRAINING_GROUPS)
        ),
        StateFilter(
            TrainerAssignmentStates.viewing_assigned_group,
            TrainerAssignmentStates.selecting_trainer,
        ),
    )
    router.callback_query.register(
        handle_select_trainer,
        F.data.startswith(SELECT_TRAINER_PREFIX),
        TrainerAssignmentStates.selecting_trainer,
    )
    router.callback_query.register(
        handle_back_to_trainer_candidates,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.TRAINER_CANDIDATES)
        ),
        TrainerAssignmentStates.confirming,
    )
    router.callback_query.register(
        handle_confirm_trainer_assignment,
        F.data == CONFIRM_ASSIGN_TRAINER_ACTION,
        TrainerAssignmentStates.confirming,
    )
    return router


async def _show_groups(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    groups_interactor: ListTrainingGroupsInteractor,
    renderer: TelegramScreenRenderer,
    mode: RenderMode,
) -> None:
    groups = await _load_groups(
        actor_telegram_id=actor_telegram_id,
        groups_interactor=groups_interactor,
        message=message,
        state=state,
        renderer=renderer,
        mode=mode,
    )
    if groups is None:
        return
    await state.set_state(TrainerAssignmentStates.selecting_group)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=(
            f"{SELECT_GROUP_TEXT}\n\n"
            f"{format_training_group_selection_details(groups)}"
            if groups
            else NO_GROUPS_TEXT
        ),
        reply_markup=build_group_selection_keyboard(groups),
        mode=mode,
    )


async def _show_trainers(
    message: Message,
    state: FSMContext,
    group: TrainingGroupSummary,
    trainers: tuple[BotUserSummary, ...],
    renderer: TelegramScreenRenderer,
) -> None:
    await state.set_state(TrainerAssignmentStates.selecting_trainer)
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=build_trainer_selection_screen(group, trainers),
        mode=RenderMode.EDIT,
        editable_message=message,
    )


async def _show_assigned_group(
    message: Message,
    state: FSMContext,
    group: TrainingGroupSummary,
    renderer: TelegramScreenRenderer,
) -> None:
    trainer_name = (
        group.trainer.display_name
        if group.trainer is not None
        else "данные пользователя недоступны"
    )
    await set_flow_context(
        state,
        {"training_group_id": group.training_group_id},
    )
    await state.set_state(TrainerAssignmentStates.viewing_assigned_group)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=(
            f"{TITLE}\n\nГруппа:\n{format_training_group_details(group)}\n\n"
            f"Тренер уже назначен:\n{trainer_name}"
        ),
        reply_markup=build_inline_keyboard(
            (
                build_back_button(NavigationTarget.TRAINING_GROUPS),
                build_cancel_button(),
            )
        ),
    )


async def _load_selection_context(
    *,
    actor_telegram_id: int,
    training_group_id: int,
    trainer_user_id: int,
    groups_interactor: ListTrainingGroupsInteractor,
    trainers_interactor: ListTrainerCandidatesInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> tuple[TrainingGroupSummary, BotUserSummary] | None:
    context = await _load_group_and_trainers(
        actor_telegram_id=actor_telegram_id,
        training_group_id=training_group_id,
        groups_interactor=groups_interactor,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if context is None:
        return None
    group, trainers = context
    trainer = _find_trainer(trainers, trainer_user_id)
    if trainer is None:
        await _show_trainer_unavailable(message, state, renderer)
        return None
    return group, trainer


async def _load_group_and_trainers(
    *,
    actor_telegram_id: int,
    training_group_id: int,
    groups_interactor: ListTrainingGroupsInteractor,
    trainers_interactor: ListTrainerCandidatesInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> tuple[TrainingGroupSummary, tuple[BotUserSummary, ...]] | None:
    groups = await _load_groups(
        actor_telegram_id=actor_telegram_id,
        groups_interactor=groups_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if groups is None:
        return None
    group = _find_group(groups, training_group_id)
    if group is None:
        await _show_group_unavailable(message, state, renderer)
        return None
    trainers = await _load_trainers(
        actor_telegram_id=actor_telegram_id,
        trainers_interactor=trainers_interactor,
        message=message,
        state=state,
        renderer=renderer,
    )
    if trainers is None:
        return None
    return group, trainers


async def _load_groups(
    *,
    actor_telegram_id: int,
    groups_interactor: ListTrainingGroupsInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    mode: RenderMode = RenderMode.EDIT,
) -> tuple[TrainingGroupSummary, ...] | None:
    try:
        return await groups_interactor(
            ListTrainingGroupsQuery(actor_telegram_id=actor_telegram_id)
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_permission_denied(
            message,
            state,
            renderer,
            mode=mode,
        )
        return None


async def _load_trainers(
    *,
    actor_telegram_id: int,
    trainers_interactor: ListTrainerCandidatesInteractor,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> tuple[BotUserSummary, ...] | None:
    try:
        return await trainers_interactor(
            ListTrainerCandidatesQuery(actor_telegram_id=actor_telegram_id)
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_permission_denied(message, state, renderer)
        return None


async def _show_group_unavailable(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> None:
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=GROUP_UNAVAILABLE_TEXT,
        reply_markup=build_inline_keyboard((build_menu_button(),)),
    )


async def _show_trainer_unavailable(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> None:
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=TRAINER_UNAVAILABLE_TEXT,
        reply_markup=build_inline_keyboard((build_menu_button(),)),
    )


async def _show_permission_denied(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    *,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=PERMISSION_DENIED_TEXT,
        reply_markup=build_inline_keyboard((build_menu_button(),)),
        mode=mode,
    )


async def _cancel_assignment(
    *,
    message: Message,
    state: FSMContext,
    telegram_id: int | None,
    menu_interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
) -> None:
    await clear_flow_context(state)
    if telegram_id is None:
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=ASSIGNMENT_CANCELLED_TEXT,
            reply_markup=None,
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
        notice=ASSIGNMENT_CANCELLED_TEXT,
        mode=RenderMode.NEW,
    )


async def _render_admin_screen(
    *,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=TelegramScreen(
            text=text,
            reply_markup=reply_markup,
            banner=BannerContext.ADMIN_PANEL,
        ),
        mode=mode,
        editable_message=message,
    )


def _confirmation_text(
    group: TrainingGroupSummary,
    trainer: BotUserSummary,
) -> str:
    return (
        "Назначить тренера?\n\n"
        f"Группа:\n{format_training_group_details(group)}\n\n"
        f"Тренер:\n{trainer.display_name}"
    )


def _success_text(
    group: TrainingGroupSummary,
    trainer: BotUserSummary,
) -> str:
    return (
        "Тренер назначен\n\n"
        f"Группа:\n{format_training_group_details(group)}\n\n"
        f"Тренер:\n{trainer.display_name}"
    )


def _find_group(
    groups: tuple[TrainingGroupSummary, ...],
    training_group_id: int,
) -> TrainingGroupSummary | None:
    return next(
        (
            group
            for group in groups
            if group.training_group_id == training_group_id
        ),
        None,
    )


def _find_trainer(
    trainers: tuple[BotUserSummary, ...],
    trainer_user_id: int,
) -> BotUserSummary | None:
    return next(
        (
            trainer
            for trainer in trainers
            if trainer.user_id == trainer_user_id
        ),
        None,
    )


def _parse_id(data: str, prefix: str) -> int | None:
    try:
        return int(data.removeprefix(prefix))
    except ValueError:
        return None


def _flow_id(flow_context: dict[str, object], key: str) -> int | None:
    value = flow_context.get(key)
    return value if isinstance(value, int) else None
