from aiogram import F, Router
from aiogram.filters import Command
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
    SearchBotUsersInteractor,
    SearchBotUsersQuery,
)
from application.identity.errors import (
    AdministratorPermissionRequiredError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import SystemRoleCode
from presentation.telegram.states import RoleManagementStates

MANAGE_USERS_ACTION = "administrator.manage_users"
SELECT_USER_PREFIX = "user_roles.select:"
BEGIN_ASSIGN_ROLE_ACTION = "user_roles.assign:start"
ASSIGN_ROLE_PREFIX = "user_roles.assign_role:"

ENTER_USER_QUERY_TEXT = (
    "Введите имя, фамилию или Telegram username пользователя. "
    "Для отмены отправьте /cancel."
)
INVALID_USER_QUERY_TEXT = "Введите непустое имя или Telegram username."
NO_USERS_FOUND_TEXT = "Пользователи не найдены. Попробуйте другой запрос."
SELECT_USER_TEXT = "Выберите зарегистрированного пользователя."
ROLE_MANAGEMENT_CANCELLED_TEXT = "Управление ролями отменено."
ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT = (
    "Действие доступно только администратору."
)
USER_SELECTION_UNAVAILABLE_TEXT = (
    "Пользователь больше не доступен. Выполните поиск заново."
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_user_label(user),
                    callback_data=f"{SELECT_USER_PREFIX}{user.user_id}",
                )
            ]
            for user in users
        ]
    )


def build_begin_assignment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назначить роль",
                    callback_data=BEGIN_ASSIGN_ROLE_ACTION,
                )
            ]
        ]
    )


def build_role_selection_keyboard(
    role_codes: tuple[SystemRoleCode, ...],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=role_code.value,
                    callback_data=f"{ASSIGN_ROLE_PREFIX}{role_code.value}",
                )
            ]
            for role_code in role_codes
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
    await message.answer(ENTER_USER_QUERY_TEXT)


async def handle_cancel_role_management(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await message.answer(ROLE_MANAGEMENT_CANCELLED_TEXT)


@inject
async def handle_search_bot_users(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[SearchBotUsersInteractor],
) -> None:
    telegram_user = message.from_user
    query = message.text.strip() if message.text is not None else ""
    if telegram_user is None or not query:
        await message.answer(INVALID_USER_QUERY_TEXT)
        return

    try:
        result = await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=telegram_user.id,
                query=query,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await state.clear()
        await message.answer(ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT)
        return

    if not result.users:
        await message.answer(NO_USERS_FOUND_TEXT)
        return

    await state.update_data(search_query=query)
    await state.set_state(RoleManagementStates.waiting_for_user_selection)
    await message.answer(
        SELECT_USER_TEXT,
        reply_markup=build_user_selection_keyboard(result.users),
    )


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

    try:
        target_user_id = int(
            callback.data.removeprefix(SELECT_USER_PREFIX)
        )
    except ValueError:
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    data = await state.get_data()
    search_query = data.get("search_query")
    if not isinstance(search_query, str):
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    try:
        result = await interactor(
            SearchBotUsersQuery(
                actor_telegram_id=callback.from_user.id,
                query=search_query,
            )
        )
    except (AdministratorPermissionRequiredError, UserNotFoundError):
        await state.clear()
        await message.answer(ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT)
        return

    target = next(
        (
            user
            for user in result.users
            if user.user_id == target_user_id
        ),
        None,
    )
    if target is None:
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    await state.update_data(
        target_user_id=target.user_id,
        target_user_label=_user_label(target),
        assignable_role_codes=[
            role_code.value
            for role_code in result.assignable_role_codes
        ],
    )
    await state.set_state(RoleManagementStates.viewing_user)
    await message.answer(
        USER_ROLE_CONTEXT_TEXT.format(
            user=_user_label(target),
            roles=_roles_text(target.role_codes),
        ),
        reply_markup=build_begin_assignment_keyboard(),
    )


async def handle_begin_role_assignment(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    data = await state.get_data()
    target_user_label = data.get("target_user_label")
    raw_role_codes = data.get("assignable_role_codes")
    if not isinstance(target_user_label, str) or not isinstance(
        raw_role_codes, list
    ):
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    try:
        role_codes = tuple(SystemRoleCode(code) for code in raw_role_codes)
    except (TypeError, ValueError):
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    await state.set_state(RoleManagementStates.waiting_for_role_selection)
    await message.answer(
        SELECT_ROLE_TEXT.format(user=target_user_label),
        reply_markup=build_role_selection_keyboard(role_codes),
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

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    if not isinstance(target_user_id, int):
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return

    try:
        role_code = SystemRoleCode(
            callback.data.removeprefix(ASSIGN_ROLE_PREFIX)
        )
    except ValueError:
        await message.answer(ROLE_CONFIGURATION_UNAVAILABLE_TEXT)
        return

    try:
        result = await interactor(
            AssignUserRoleCommand(
                actor_telegram_id=callback.from_user.id,
                target_user_id=target_user_id,
                role_code=role_code,
            )
        )
    except AdministratorPermissionRequiredError:
        await state.clear()
        await message.answer(ROLE_MANAGEMENT_PERMISSION_DENIED_TEXT)
        return
    except UserNotFoundError:
        await state.clear()
        await message.answer(USER_SELECTION_UNAVAILABLE_TEXT)
        return
    except RequiredSystemRoleMissingError:
        await message.answer(ROLE_CONFIGURATION_UNAVAILABLE_TEXT)
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
        )
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
        RoleManagementStates.waiting_for_query,
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
        handle_begin_role_assignment,
        F.data == BEGIN_ASSIGN_ROLE_ACTION,
        RoleManagementStates.viewing_user,
    )
    router.callback_query.register(
        handle_assign_user_role,
        F.data.startswith(ASSIGN_ROLE_PREFIX),
        RoleManagementStates.waiting_for_role_selection,
    )
    return router


def _user_label(user: BotUserSummary) -> str:
    if user.username is None:
        return user.display_name
    return f"{user.display_name} (@{user.username})"


def _roles_text(role_codes: tuple[SystemRoleCode, ...]) -> str:
    if not role_codes:
        return "нет"
    return "\n".join(role_code.value for role_code in role_codes)
