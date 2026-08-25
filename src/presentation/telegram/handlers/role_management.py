from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    AssignUserRoleCommand,
    AssignUserRoleInteractor,
    BotUserSummary,
    GetUserMenuContextInteractor,
    RemoveUserRoleCommand,
    RemoveUserRoleInteractor,
    SearchBotUsersInteractor,
    SearchBotUsersQuery,
    SearchBotUsersResult,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    LastUserRoleRemovalForbiddenError,
    OwnerRoleManagementForbiddenError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import SystemRoleCode
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
from presentation.telegram.screen import (
    BannerContext,
    RenderMode,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.states import RoleManagementStates
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_flow_context,
    set_flow_context,
    update_flow_context,
)

MANAGE_USERS_ACTION = "administrator.manage_users"
SELECT_USER_PREFIX = "user_roles.select:"
BEGIN_ASSIGN_ROLE_PREFIX = "user_roles.assign:start:"
ASSIGN_ROLE_PREFIX = "user_roles.assign_role:"
BEGIN_REMOVE_ROLE_PREFIX = "user_roles.remove:start:"
REMOVE_ROLE_PREFIX = "user_roles.remove_role:"

ENTER_USER_QUERY_TEXT = (
    "Введите имя, фамилию или Telegram username пользователя."
)
INVALID_USER_QUERY_TEXT = "Введите непустое имя или Telegram username."
NO_USERS_FOUND_TEXT = "Пользователи не найдены. Попробуйте другой запрос."
SELECT_USER_TEXT = "Выберите зарегистрированного пользователя."
ROLE_MANAGEMENT_CANCELLED_TEXT = "Управление ролями отменено."
ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору или владельцу."
)
USER_SELECTION_UNAVAILABLE_TEXT = (
    "Пользователь больше не доступен. Вернитесь в актуальную панель."
)
ROLE_CONFIGURATION_UNAVAILABLE_TEXT = (
    "Выбранная системная роль сейчас недоступна. Обратитесь к администратору "
    "системы."
)
USER_ROLE_CONTEXT_TEXT = "Пользователь: {user}\nТекущие роли:\n{roles}"
SELECT_ROLE_TEXT = "Выберите системную роль для назначения пользователю {user}."
SELECT_ROLE_TO_REMOVE_TEXT = "Выберите роль, которую нужно снять у {user}."
ROLE_ASSIGNED_TEXT = "Роль {role} назначена.\nТекущие роли:\n{roles}"
ROLE_ALREADY_ASSIGNED_TEXT = (
    "Роль {role} уже назначена.\nТекущие роли:\n{roles}"
)
ROLE_REMOVED_TEXT = "Роль {role} снята."
ROLE_ALREADY_ABSENT_TEXT = "Роль {role} уже отсутствует."
LAST_ROLE_REMOVAL_FORBIDDEN_TEXT = "Нельзя снять последнюю роль пользователя."
OWNER_ROLE_MANAGEMENT_FORBIDDEN_TEXT = (
    "Роль OWNER назначается только системным оператором и недоступна для "
    "управления через Telegram."
)


def build_user_selection_keyboard(
    users: tuple[BotUserSummary, ...],
) -> InlineKeyboardMarkup:
    user_rows = tuple(
        (
            build_callback_button(
                text=_user_label(user),
                callback_data=f"{SELECT_USER_PREFIX}{user.user_id}",
            ),
        )
        for user in users
    )
    return build_inline_keyboard(
        *user_rows,
        (build_back_button(NavigationTarget.ROLE_PANEL),),
    )


def build_user_profile_keyboard(
    target_user_id: int,
    role_codes: tuple[SystemRoleCode, ...],
) -> InlineKeyboardMarkup:
    action_buttons = [
        build_callback_button(
            text="Назначить роль",
            callback_data=f"{BEGIN_ASSIGN_ROLE_PREFIX}{target_user_id}",
        )
    ]
    if len(role_codes) > 1 and any(
        code is not SystemRoleCode.OWNER for code in role_codes
    ):
        action_buttons.append(
            build_callback_button(
                text="Снять роль",
                callback_data=f"{BEGIN_REMOVE_ROLE_PREFIX}{target_user_id}",
            )
        )
    return build_inline_keyboard(
        tuple(action_buttons),
        (build_back_button(NavigationTarget.USERS_LIST),),
        (build_cancel_button(),),
    )


def build_role_selection_keyboard(
    target_user_id: int,
    role_codes: tuple[SystemRoleCode, ...],
) -> InlineKeyboardMarkup:
    role_buttons = tuple(
        build_callback_button(
            text=role_code.value,
            callback_data=(
                f"{ASSIGN_ROLE_PREFIX}{target_user_id}:{role_code.value}"
            ),
        )
        for role_code in role_codes
        if role_code is not SystemRoleCode.OWNER
    )
    role_rows = tuple(
        role_buttons[index : index + 2]
        for index in range(0, len(role_buttons), 2)
    )
    return build_inline_keyboard(
        *role_rows,
        (
            build_back_button(
                NavigationTarget.USER_PROFILE,
                target_id=target_user_id,
            ),
        ),
        (build_cancel_button(),),
    )


def build_role_removal_keyboard(
    target_user_id: int,
    role_codes: tuple[SystemRoleCode, ...],
) -> InlineKeyboardMarkup:
    role_buttons = tuple(
        build_callback_button(
            text=role_code.value,
            callback_data=(
                f"{REMOVE_ROLE_PREFIX}{target_user_id}:{role_code.value}"
            ),
        )
        for role_code in role_codes
        if role_code is not SystemRoleCode.OWNER
    )
    role_rows = tuple(
        role_buttons[index : index + 2]
        for index in range(0, len(role_buttons), 2)
    )
    return build_inline_keyboard(
        *role_rows,
        (
            build_back_button(
                NavigationTarget.USER_PROFILE,
                target_id=target_user_id,
            ),
        ),
        (build_cancel_button(),),
    )


@inject
async def handle_begin_user_search(
    callback: CallbackQuery,
    state: FSMContext,
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await set_administrative_navigation_context(state)
    await set_flow_context(state, {})
    await state.set_state(RoleManagementStates.waiting_for_query)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=ENTER_USER_QUERY_TEXT,
        reply_markup=build_inline_keyboard((build_cancel_button(),)),
        mode=RenderMode.NEW,
        editable_message=message,
    )


@inject
async def handle_cancel_role_management(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    await _cancel_role_management(
        message=message,
        state=state,
        telegram_id=telegram_user.id if telegram_user is not None else None,
        menu_interactor=menu_interactor,
        renderer=renderer,
        editable_message=None,
    )


@inject
async def handle_cancel_role_management_callback(
    callback: CallbackQuery,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await _cancel_role_management(
        message=message,
        state=state,
        telegram_id=callback.from_user.id,
        menu_interactor=menu_interactor,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_search_bot_users(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    query = message.text.strip() if message.text is not None else ""
    if telegram_user is None or not query:
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=INVALID_USER_QUERY_TEXT,
            reply_markup=build_inline_keyboard((build_cancel_button(),)),
            mode=RenderMode.NEW,
        )
        return

    try:
        result = await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=telegram_user.id,
                query=query,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_permission_denied(
            message=message,
            state=state,
            renderer=renderer,
            mode=RenderMode.NEW,
        )
        return

    await set_flow_context(state, {"search_query": query})
    if not result.users:
        await state.set_state(RoleManagementStates.waiting_for_query)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=NO_USERS_FOUND_TEXT,
            reply_markup=build_inline_keyboard((build_cancel_button(),)),
            mode=RenderMode.NEW,
        )
        return
    await _show_users_list(
        message=message,
        state=state,
        result=result,
        renderer=renderer,
        mode=RenderMode.NEW,
    )


@inject
async def handle_select_bot_user(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    target_user_id = _parse_target_user_id(
        callback.data,
        prefix=SELECT_USER_PREFIX,
    )
    if target_user_id is None:
        await _show_user_unavailable(message, state, renderer)
        return

    search_context = await _load_search_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        interactor=interactor,
        renderer=renderer,
    )
    if search_context is None:
        return
    _, result = search_context

    target = _find_user(result, target_user_id)
    if target is None:
        await _show_user_unavailable(message, state, renderer)
        return
    await _show_user_profile(message, state, target, renderer)


@inject
async def handle_back_to_users_list(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    search_context = await _load_search_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        interactor=interactor,
        renderer=renderer,
    )
    if search_context is None:
        return
    query, result = search_context
    await set_flow_context(state, {"search_query": query})
    if not result.users:
        await state.set_state(RoleManagementStates.waiting_for_query)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=NO_USERS_FOUND_TEXT,
            reply_markup=build_inline_keyboard((build_cancel_button(),)),
            editable_message=message,
        )
        return
    await _show_users_list(
        message=message,
        state=state,
        result=result,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_begin_role_assignment(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    target_user_id = _parse_target_user_id(
        callback.data,
        prefix=BEGIN_ASSIGN_ROLE_PREFIX,
    )
    if target_user_id is None:
        await _show_user_unavailable(message, state, renderer)
        return

    target_context = await _load_target_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        expected_target_user_id=target_user_id,
        interactor=interactor,
        renderer=renderer,
    )
    if target_context is None:
        return
    target, result = target_context

    await state.set_state(RoleManagementStates.waiting_for_role_selection)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=SELECT_ROLE_TEXT.format(user=_user_label(target)),
        reply_markup=build_role_selection_keyboard(
            target.user_id,
            result.assignable_role_codes,
        ),
        editable_message=message,
    )


@inject
async def handle_begin_role_removal(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    target_user_id = _parse_target_user_id(
        callback.data,
        prefix=BEGIN_REMOVE_ROLE_PREFIX,
    )
    if target_user_id is None:
        await _show_user_unavailable(message, state, renderer)
        return

    target_context = await _load_target_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        expected_target_user_id=target_user_id,
        interactor=interactor,
        renderer=renderer,
    )
    if target_context is None:
        return
    target, _ = target_context
    if len(target.role_codes) < 2:
        await _show_user_profile(
            message,
            state,
            target,
            renderer,
            editable_message=message,
            notice=LAST_ROLE_REMOVAL_FORBIDDEN_TEXT,
        )
        return

    await state.set_state(
        RoleManagementStates.waiting_for_role_removal_selection
    )
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=SELECT_ROLE_TO_REMOVE_TEXT.format(user=_user_label(target)),
        reply_markup=build_role_removal_keyboard(
            target.user_id,
            target.role_codes,
        ),
        editable_message=message,
    )


@inject
async def handle_back_to_user_profile(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    try:
        navigation = NavigationCallback.unpack(callback.data)
    except ValueError:
        await _show_user_unavailable(message, state, renderer)
        return
    if navigation.target_id is None:
        await _show_user_unavailable(message, state, renderer)
        return

    target_context = await _load_target_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        expected_target_user_id=navigation.target_id,
        interactor=interactor,
        renderer=renderer,
    )
    if target_context is None:
        return
    target, _ = target_context
    await _show_user_profile(
        message,
        state,
        target,
        renderer,
        editable_message=message,
    )


@inject
async def handle_assign_user_role(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[AssignUserRoleInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    assignment = _parse_role_assignment(callback.data)
    flow_context = await get_flow_context(state)
    state_target_user_id = flow_context.get("target_user_id")
    if (
        assignment is None
        or not isinstance(state_target_user_id, int)
        or state_target_user_id != assignment[0]
    ):
        await _show_user_unavailable(message, state, renderer)
        return
    target_user_id, role_code = assignment

    try:
        result = await interactor(
            AssignUserRoleCommand(
                actor_telegram_id=callback.from_user.id,
                target_user_id=target_user_id,
                role_code=role_code,
            )
        )
    except AdministratorPermissionRequiredError:
        await _show_permission_denied(message, state, renderer)
        return
    except UserNotFoundError:
        await _show_user_unavailable(message, state, renderer)
        return
    except RequiredSystemRoleMissingError:
        await clear_flow_context(state)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=ROLE_CONFIGURATION_UNAVAILABLE_TEXT,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
            editable_message=message,
        )
        return
    except OwnerRoleManagementForbiddenError:
        await clear_flow_context(state)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=OWNER_ROLE_MANAGEMENT_FORBIDDEN_TEXT,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
            editable_message=message,
        )
        return

    response_template = (
        ROLE_ASSIGNED_TEXT
        if result.role_was_assigned
        else ROLE_ALREADY_ASSIGNED_TEXT
    )
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=response_template.format(
            role=result.role_code.value,
            roles=_roles_text(result.current_role_codes),
        ),
        reply_markup=build_inline_keyboard((build_menu_button(),)),
        editable_message=message,
    )


@inject
async def handle_remove_user_role(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[RemoveUserRoleInteractor],
    search_interactor: FromDishka[SearchBotUsersInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    removal = _parse_role_action(callback.data, prefix=REMOVE_ROLE_PREFIX)
    flow_context = await get_flow_context(state)
    state_target_user_id = flow_context.get("target_user_id")
    if (
        removal is None
        or not isinstance(state_target_user_id, int)
        or state_target_user_id != removal[0]
    ):
        await _show_user_unavailable(message, state, renderer)
        return
    target_user_id, role_code = removal

    try:
        result = await interactor(
            RemoveUserRoleCommand(
                actor_telegram_id=callback.from_user.id,
                target_user_id=target_user_id,
                role_code=role_code,
            )
        )
    except AdministratorPermissionRequiredError:
        await _show_permission_denied(message, state, renderer)
        return
    except UserNotFoundError:
        await _show_user_unavailable(message, state, renderer)
        return
    except RequiredSystemRoleMissingError:
        await clear_flow_context(state)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=ROLE_CONFIGURATION_UNAVAILABLE_TEXT,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
            editable_message=message,
        )
        return
    except OwnerRoleManagementForbiddenError:
        await clear_flow_context(state)
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=OWNER_ROLE_MANAGEMENT_FORBIDDEN_TEXT,
            reply_markup=build_inline_keyboard((build_menu_button(),)),
            editable_message=message,
        )
        return
    except LastUserRoleRemovalForbiddenError:
        target_context = await _load_target_context(
            message=message,
            state=state,
            actor_telegram_id=callback.from_user.id,
            expected_target_user_id=target_user_id,
            interactor=search_interactor,
            renderer=renderer,
        )
        if target_context is None:
            return
        target, _ = target_context
        await _show_user_profile(
            message,
            state,
            target,
            renderer,
            editable_message=message,
            notice=LAST_ROLE_REMOVAL_FORBIDDEN_TEXT,
        )
        return

    notice_template = (
        ROLE_REMOVED_TEXT
        if result.role_was_removed
        else ROLE_ALREADY_ABSENT_TEXT
    )
    await _show_user_profile(
        message,
        state,
        result.target_user,
        renderer,
        editable_message=message,
        notice=notice_template.format(role=result.role_code.value),
    )


def create_role_management_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_begin_user_search,
        F.data == MANAGE_USERS_ACTION,
    )
    router.message.register(
        handle_cancel_role_management,
        Command("cancel"),
        StateFilter(RoleManagementStates),
    )
    router.callback_query.register(
        handle_cancel_role_management_callback,
        NavigationCallback.filter(
            (F.action == NavigationAction.CANCEL)
            & (F.target == NavigationTarget.ROLE_PANEL)
        ),
        StateFilter(RoleManagementStates),
    )
    router.message.register(
        handle_search_bot_users,
        RoleManagementStates.waiting_for_query,
    )
    router.callback_query.register(
        handle_select_bot_user,
        F.data.startswith(SELECT_USER_PREFIX),
        RoleManagementStates.waiting_for_user_selection,
    )
    router.callback_query.register(
        handle_back_to_users_list,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.USERS_LIST)
        ),
        RoleManagementStates.viewing_user,
    )
    router.callback_query.register(
        handle_begin_role_assignment,
        F.data.startswith(BEGIN_ASSIGN_ROLE_PREFIX),
        RoleManagementStates.viewing_user,
    )
    router.callback_query.register(
        handle_begin_role_removal,
        F.data.startswith(BEGIN_REMOVE_ROLE_PREFIX),
        RoleManagementStates.viewing_user,
    )
    router.callback_query.register(
        handle_back_to_user_profile,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.USER_PROFILE)
        ),
        StateFilter(
            RoleManagementStates.waiting_for_role_selection,
            RoleManagementStates.waiting_for_role_removal_selection,
        ),
    )
    router.callback_query.register(
        handle_assign_user_role,
        F.data.startswith(ASSIGN_ROLE_PREFIX),
        RoleManagementStates.waiting_for_role_selection,
    )
    router.callback_query.register(
        handle_remove_user_role,
        F.data.startswith(REMOVE_ROLE_PREFIX),
        RoleManagementStates.waiting_for_role_removal_selection,
    )
    return router


async def _cancel_role_management(
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
        await _render_admin_screen(
            message=message,
            state=state,
            renderer=renderer,
            text=ROLE_MANAGEMENT_CANCELLED_TEXT,
            reply_markup=None,
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
        notice=ROLE_MANAGEMENT_CANCELLED_TEXT,
    )


async def _load_search_context(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    interactor: SearchBotUsersInteractor,
    renderer: TelegramScreenRenderer,
) -> tuple[str, SearchBotUsersResult] | None:
    flow_context = await get_flow_context(state)
    search_query = flow_context.get("search_query")
    if not isinstance(search_query, str):
        await _show_user_unavailable(message, state, renderer)
        return None

    try:
        result = await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=actor_telegram_id,
                query=search_query,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_permission_denied(message, state, renderer)
        return None
    return search_query, result


async def _load_target_context(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    expected_target_user_id: int,
    interactor: SearchBotUsersInteractor,
    renderer: TelegramScreenRenderer,
) -> tuple[BotUserSummary, SearchBotUsersResult] | None:
    flow_context = await get_flow_context(state)
    state_target_user_id = flow_context.get("target_user_id")
    if (
        not isinstance(state_target_user_id, int)
        or state_target_user_id != expected_target_user_id
    ):
        await _show_user_unavailable(message, state, renderer)
        return None

    search_context = await _load_search_context(
        message=message,
        state=state,
        actor_telegram_id=actor_telegram_id,
        interactor=interactor,
        renderer=renderer,
    )
    if search_context is None:
        return None
    _, result = search_context
    target = _find_user(result, state_target_user_id)
    if target is None:
        await _show_user_unavailable(message, state, renderer)
        return None
    return target, result


async def _show_users_list(
    message: Message,
    state: FSMContext,
    result: SearchBotUsersResult,
    renderer: TelegramScreenRenderer,
    *,
    mode: RenderMode = RenderMode.EDIT,
    editable_message: Message | None = None,
) -> None:
    await state.set_state(RoleManagementStates.waiting_for_user_selection)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=SELECT_USER_TEXT,
        reply_markup=build_user_selection_keyboard(result.users),
        mode=mode,
        editable_message=editable_message,
    )


async def _show_user_profile(
    message: Message,
    state: FSMContext,
    target: BotUserSummary,
    renderer: TelegramScreenRenderer,
    *,
    editable_message: Message | None = None,
    notice: str | None = None,
) -> None:
    await update_flow_context(state, target_user_id=target.user_id)
    await state.set_state(RoleManagementStates.viewing_user)
    profile_text = USER_ROLE_CONTEXT_TEXT.format(
        user=_user_label(target),
        roles=_roles_text(target.role_codes),
    )
    if notice:
        profile_text = f"{notice}\n\n{profile_text}"
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=profile_text,
        reply_markup=build_user_profile_keyboard(
            target.user_id,
            target.role_codes,
        ),
        editable_message=editable_message,
    )


async def _show_user_unavailable(
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
) -> None:
    await clear_flow_context(state)
    await _render_admin_screen(
        message=message,
        state=state,
        renderer=renderer,
        text=USER_SELECTION_UNAVAILABLE_TEXT,
        reply_markup=build_inline_keyboard((build_menu_button(),)),
        editable_message=message,
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
        text=ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT,
        reply_markup=build_inline_keyboard((build_menu_button(),)),
        mode=mode,
        editable_message=message,
    )


async def _render_admin_screen(
    *,
    message: Message,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    mode: RenderMode = RenderMode.EDIT,
    editable_message: Message | None = None,
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
        editable_message=editable_message,
    )


def _find_user(
    result: SearchBotUsersResult,
    target_user_id: int,
) -> BotUserSummary | None:
    return next(
        (
            user
            for user in result.users
            if user.user_id == target_user_id
        ),
        None,
    )


def _parse_target_user_id(data: str, *, prefix: str) -> int | None:
    try:
        return int(data.removeprefix(prefix))
    except ValueError:
        return None


def _parse_role_assignment(
    data: str,
) -> tuple[int, SystemRoleCode] | None:
    return _parse_role_action(data, prefix=ASSIGN_ROLE_PREFIX)


def _parse_role_action(
    data: str,
    *,
    prefix: str,
) -> tuple[int, SystemRoleCode] | None:
    raw_target_user_id, separator, raw_role_code = data.removeprefix(
        prefix
    ).partition(":")
    if not separator:
        return None
    try:
        return int(raw_target_user_id), SystemRoleCode(raw_role_code)
    except ValueError:
        return None


def _user_label(user: BotUserSummary) -> str:
    if user.username is None:
        return user.display_name
    return f"{user.display_name} (@{user.username})"


def _roles_text(role_codes: tuple[SystemRoleCode, ...]) -> str:
    if not role_codes:
        return "нет"
    return "\n".join(role_code.value for role_code in role_codes)
