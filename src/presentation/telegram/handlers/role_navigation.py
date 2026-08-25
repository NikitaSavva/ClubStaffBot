import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
    ListUnlinkedAthletesInteractor,
)
from presentation.telegram.handlers.account_link import (
    LINK_ACCOUNT_ACTION,
    show_unlinked_athletes,
)
from presentation.telegram.handlers.athlete_creation import (
    CREATE_ATHLETE_ACTION,
    begin_create_athlete_flow,
)
from presentation.telegram.handlers.menu import (
    load_menu_context,
    show_home_screen,
)
from presentation.telegram.handlers.role_management import (
    MANAGE_USERS_ACTION,
    begin_user_search_flow,
)
from presentation.telegram.keyboards.role import (
    ROLE_SWITCH_ACTION,
    RoleReplyAction,
    RoleReplyKeyboardBuilder,
    role_reply_labels,
)
from presentation.telegram.presenters import RolePanel, available_role_panels
from presentation.telegram.screen import TelegramScreenRenderer
from presentation.telegram.ui_context import (
    clear_flow_context,
    get_navigation_context,
)

logger = structlog.get_logger()

_role_reply_keyboard_builder = RoleReplyKeyboardBuilder()


@inject
async def handle_role_reply_action(
    message: Message,
    state: FSMContext,
    menu_interactor: FromDishka[GetUserMenuContextInteractor],
    list_unlinked_athletes_interactor: FromDishka[
        ListUnlinkedAthletesInteractor
    ],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    text = message.text
    if telegram_user is None or text is None:
        return

    context = await load_menu_context(
        telegram_id=telegram_user.id,
        interactor=menu_interactor,
    )
    if context is None:
        return
    roles = available_role_panels(context)
    role = await _resolve_active_role(state, roles)
    if role is None:
        return
    action = _role_reply_keyboard_builder.resolve(
        context,
        role,
        is_multi_role=len(roles) > 1,
        text=text,
    )
    if action is None:
        return

    await clear_flow_context(state)
    await delete_role_navigation_message(message)
    await _open_role_action(
        action=action,
        message=message,
        telegram_id=telegram_user.id,
        state=state,
        menu_interactor=menu_interactor,
        list_unlinked_athletes_interactor=(
            list_unlinked_athletes_interactor
        ),
        renderer=renderer,
    )


async def delete_role_navigation_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as error:
        logger.warning(
            "telegram_role_navigation_message_delete_failed",
            chat_id=message.chat.id,
            message_id=message.message_id,
            error_type=type(error).__name__,
        )


async def _resolve_active_role(
    state: FSMContext,
    roles: tuple[RolePanel, ...],
) -> RolePanel | None:
    navigation = await get_navigation_context(state)
    try:
        active_role = (
            RolePanel(navigation.active_role)
            if navigation is not None and navigation.active_role is not None
            else None
        )
    except ValueError:
        active_role = None
    if active_role in roles:
        return active_role
    if len(roles) == 1:
        return roles[0]
    return None


async def _open_role_action(
    *,
    action: RoleReplyAction,
    message: Message,
    telegram_id: int,
    state: FSMContext,
    menu_interactor: GetUserMenuContextInteractor,
    list_unlinked_athletes_interactor: ListUnlinkedAthletesInteractor,
    renderer: TelegramScreenRenderer,
) -> None:
    if action.action_id == ROLE_SWITCH_ACTION:
        await show_home_screen(
            chat_id=message.chat.id,
            telegram_id=telegram_id,
            state=state,
            interactor=menu_interactor,
            renderer=renderer,
        )
        return
    if action.action_id == CREATE_ATHLETE_ACTION:
        await begin_create_athlete_flow(
            chat_id=message.chat.id,
            state=state,
            renderer=renderer,
        )
        return
    if action.action_id == MANAGE_USERS_ACTION:
        await begin_user_search_flow(
            chat_id=message.chat.id,
            state=state,
            renderer=renderer,
        )
        return
    if action.action_id == LINK_ACCOUNT_ACTION:
        await show_unlinked_athletes(
            chat_id=message.chat.id,
            actor_telegram_id=telegram_id,
            state=state,
            interactor=list_unlinked_athletes_interactor,
            renderer=renderer,
        )


def create_role_navigation_router() -> Router:
    router = Router(name=__name__)
    router.message.register(
        handle_role_reply_action,
        F.text.in_(role_reply_labels()),
    )
    return router
