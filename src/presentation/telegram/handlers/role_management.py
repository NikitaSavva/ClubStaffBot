from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    AssignUserRoleCommand,
    AssignUserRoleInteractor,
    BotUserSummary,
    GetUserMenuContextInteractor,
    SearchBotUsersInteractor,
    SearchBotUsersQuery,
    SearchBotUsersResult,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import SystemRoleCode
from presentation.telegram.handlers.menu import show_root_menu
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
    build_back_button,
    build_cancel_button,
    build_menu_button,
    build_single_button_keyboard,
)
from presentation.telegram.states import RoleManagementStates

MANAGE_USERS_ACTION = "administrator.manage_users"
SELECT_USER_PREFIX = "user_roles.select:"
BEGIN_ASSIGN_ROLE_PREFIX = "user_roles.assign:start:"
ASSIGN_ROLE_PREFIX = "user_roles.assign_role:"

ENTER_USER_QUERY_TEXT = (
    "Введите имя, фамилию или Telegram username пользователя."
)
INVALID_USER_QUERY_TEXT = "Введите непустое имя или Telegram username."
NO_USERS_FOUND_TEXT = "Пользователи не найдены. Попробуйте другой запрос."
SELECT_USER_TEXT = "Выберите зарегистрированного пользователя."
ROLE_MANAGEMENT_CANCELLED_TEXT = "Управление ролями отменено."
ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору."
)
USER_SELECTION_UNAVAILABLE_TEXT = (
    "Пользователь больше не доступен. Вернитесь в актуальное меню."
)
ROLE_CONFIGURATION_UNAVAILABLE_TEXT = (
    "Выбранная системная роль сейчас недоступна. Обратитесь к администратору "
    "системы."
)
USER_ROLE_CONTEXT_TEXT = "Пользователь: {user}\nТекущие роли:\n{roles}"
SELECT_ROLE_TEXT = "Выберите системную роль для назначения пользователю {user}."
ROLE_ASSIGNED_TEXT = "Роль {role} назначена.\nТекущие роли:\n{roles}"
ROLE_ALREADY_ASSIGNED_TEXT = (
    "Роль {role} уже назначена.\nТекущие роли:\n{roles}"
)


def build_user_selection_keyboard(
    users: tuple[BotUserSummary, ...],
) -> InlineKeyboardMarkup:
    user_rows = [
        [
            InlineKeyboardButton(
                text=_user_label(user),
                callback_data=f"{SELECT_USER_PREFIX}{user.user_id}",
            )
        ]
        for user in users
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=user_rows
        + [[build_back_button(NavigationTarget.MENU)]]
    )


def build_begin_assignment_keyboard(
    target_user_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назначить роль",
                    callback_data=(
                        f"{BEGIN_ASSIGN_ROLE_PREFIX}{target_user_id}"
                    ),
                )
            ],
            [build_back_button(NavigationTarget.USERS_LIST)],
            [build_cancel_button()],
        ]
    )


def build_role_selection_keyboard(
    target_user_id: int,
    role_codes: tuple[SystemRoleCode, ...],
) -> InlineKeyboardMarkup:
    role_rows = [
        [
            InlineKeyboardButton(
                text=role_code.value,
                callback_data=(
                    f"{ASSIGN_ROLE_PREFIX}{target_user_id}:"
                    f"{role_code.value}"
                ),
            )
        ]
        for role_code in role_codes
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=role_rows
        + [
            [
                build_back_button(
                    NavigationTarget.USER_PROFILE,
                    target_id=target_user_id,
                )
            ],
            [build_cancel_button()],
        ]
    )


async def handle_begin_user_search(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await state.clear()
    await state.set_state(RoleManagementStates.waiting_for_query)
    await message.answer(
        ENTER_USER_QUERY_TEXT,
        reply_markup=build_single_button_keyboard(build_cancel_button()),
    )


@inject
async def handle_cancel_role_management(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
) -> None:
    telegram_user = message.from_user
    await _cancel_role_management(
        message=message,
        state=state,
        telegram_id=telegram_user.id if telegram_user is not None else None,
        menu_interactor=menu_interactor,
    )


@inject
async def handle_cancel_role_management_callback(
    callback: CallbackQuery,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
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
    )


@inject
async def handle_search_bot_users(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
) -> None:
    telegram_user = message.from_user
    query = message.text.strip() if message.text is not None else ""
    if telegram_user is None or not query:
        await message.answer(
            INVALID_USER_QUERY_TEXT,
            reply_markup=build_single_button_keyboard(
                build_cancel_button()
            ),
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
        await _show_permission_denied(message=message, state=state)
        return

    if not result.users:
        await message.answer(
            NO_USERS_FOUND_TEXT,
            reply_markup=build_single_button_keyboard(
                build_cancel_button()
            ),
        )
        return

    await state.set_data({"search_query": query})
    await _show_users_list(message=message, state=state, result=result)


@inject
async def handle_select_bot_user(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
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
        await _show_user_unavailable(message=message, state=state)
        return

    search_context = await _load_search_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        interactor=interactor,
    )
    if search_context is None:
        return
    _, result = search_context

    target = _find_user(result, target_user_id)
    if target is None:
        await _show_user_unavailable(message=message, state=state)
        return

    await _show_user_profile(
        message=message,
        state=state,
        target=target,
    )


@inject
async def handle_back_to_users_list(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
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
    )
    if search_context is None:
        return
    query, result = search_context

    await state.set_data({"search_query": query})
    if not result.users:
        await state.set_state(RoleManagementStates.waiting_for_query)
        await message.answer(
            NO_USERS_FOUND_TEXT,
            reply_markup=build_single_button_keyboard(
                build_cancel_button()
            ),
        )
        return
    await _show_users_list(message=message, state=state, result=result)


@inject
async def handle_begin_role_assignment(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    callback_target_user_id = _parse_target_user_id(
        callback.data,
        prefix=BEGIN_ASSIGN_ROLE_PREFIX,
    )
    if callback_target_user_id is None:
        await _show_user_unavailable(message=message, state=state)
        return

    target_context = await _load_target_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        expected_target_user_id=callback_target_user_id,
        interactor=interactor,
    )
    if target_context is None:
        return
    target, result = target_context

    await state.set_state(RoleManagementStates.waiting_for_role_selection)
    await message.answer(
        SELECT_ROLE_TEXT.format(user=_user_label(target)),
        reply_markup=build_role_selection_keyboard(
            target.user_id,
            result.assignable_role_codes,
        ),
    )


@inject
async def handle_back_to_user_profile(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    try:
        navigation = NavigationCallback.unpack(callback.data)
    except ValueError:
        await _show_user_unavailable(message=message, state=state)
        return
    if navigation.target_id is None:
        await _show_user_unavailable(message=message, state=state)
        return

    target_context = await _load_target_context(
        message=message,
        state=state,
        actor_telegram_id=callback.from_user.id,
        expected_target_user_id=navigation.target_id,
        interactor=interactor,
    )
    if target_context is None:
        return
    target, _ = target_context

    await _show_user_profile(
        message=message,
        state=state,
        target=target,
    )


@inject
async def handle_assign_user_role(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[AssignUserRoleInteractor],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message) or callback.data is None:
        return

    assignment = _parse_role_assignment(callback.data)
    data = await state.get_data()
    state_target_user_id = data.get("target_user_id")
    if (
        assignment is None
        or not isinstance(state_target_user_id, int)
        or state_target_user_id != assignment[0]
    ):
        await _show_user_unavailable(message=message, state=state)
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
        await _show_permission_denied(message=message, state=state)
        return
    except UserNotFoundError:
        await _show_user_unavailable(message=message, state=state)
        return
    except RequiredSystemRoleMissingError:
        await state.clear()
        await message.answer(
            ROLE_CONFIGURATION_UNAVAILABLE_TEXT,
            reply_markup=build_single_button_keyboard(build_menu_button()),
        )
        return

    await state.clear()
    response_template = (
        ROLE_ASSIGNED_TEXT
        if result.role_was_assigned
        else ROLE_ALREADY_ASSIGNED_TEXT
    )
    await message.answer(
        response_template.format(
            role=result.role_code.value,
            roles=_roles_text(result.current_role_codes),
        ),
        reply_markup=build_single_button_keyboard(build_menu_button()),
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
            & (F.target == NavigationTarget.MENU)
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
        handle_back_to_user_profile,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.USER_PROFILE)
        ),
        RoleManagementStates.waiting_for_role_selection,
    )
    router.callback_query.register(
        handle_assign_user_role,
        F.data.startswith(ASSIGN_ROLE_PREFIX),
        RoleManagementStates.waiting_for_role_selection,
    )
    return router


async def _cancel_role_management(
    *,
    message: Message,
    state: FSMContext,
    telegram_id: int | None,
    menu_interactor: GetUserMenuContextInteractor,
) -> None:
    await state.clear()
    await message.answer(ROLE_MANAGEMENT_CANCELLED_TEXT)
    if telegram_id is not None:
        await show_root_menu(
            message=message,
            telegram_id=telegram_id,
            interactor=menu_interactor,
        )


async def _load_search_context(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    interactor: SearchBotUsersInteractor,
) -> tuple[str, SearchBotUsersResult] | None:
    data = await state.get_data()
    search_query = data.get("search_query")
    if not isinstance(search_query, str):
        await _show_user_unavailable(message=message, state=state)
        return None

    try:
        result = await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=actor_telegram_id,
                query=search_query,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await _show_permission_denied(message=message, state=state)
        return None
    return search_query, result


async def _load_target_context(
    *,
    message: Message,
    state: FSMContext,
    actor_telegram_id: int,
    expected_target_user_id: int,
    interactor: SearchBotUsersInteractor,
) -> tuple[BotUserSummary, SearchBotUsersResult] | None:
    data = await state.get_data()
    state_target_user_id = data.get("target_user_id")
    if (
        not isinstance(state_target_user_id, int)
        or state_target_user_id != expected_target_user_id
    ):
        await _show_user_unavailable(message=message, state=state)
        return None

    search_context = await _load_search_context(
        message=message,
        state=state,
        actor_telegram_id=actor_telegram_id,
        interactor=interactor,
    )
    if search_context is None:
        return None
    _, result = search_context

    target = _find_user(result, state_target_user_id)
    if target is None:
        await _show_user_unavailable(message=message, state=state)
        return None
    return target, result


async def _show_users_list(
    *,
    message: Message,
    state: FSMContext,
    result: SearchBotUsersResult,
) -> None:
    await state.set_state(RoleManagementStates.waiting_for_user_selection)
    await message.answer(
        SELECT_USER_TEXT,
        reply_markup=build_user_selection_keyboard(result.users),
    )


async def _show_user_profile(
    *,
    message: Message,
    state: FSMContext,
    target: BotUserSummary,
) -> None:
    await state.update_data(target_user_id=target.user_id)
    await state.set_state(RoleManagementStates.viewing_user)
    await message.answer(
        USER_ROLE_CONTEXT_TEXT.format(
            user=_user_label(target),
            roles=_roles_text(target.role_codes),
        ),
        reply_markup=build_begin_assignment_keyboard(target.user_id),
    )


async def _show_user_unavailable(
    *,
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(
        USER_SELECTION_UNAVAILABLE_TEXT,
        reply_markup=build_single_button_keyboard(build_menu_button()),
    )


async def _show_permission_denied(
    *,
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(
        ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT,
        reply_markup=build_single_button_keyboard(build_menu_button()),
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
    raw_target_user_id, separator, raw_role_code = data.removeprefix(
        ASSIGN_ROLE_PREFIX
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
