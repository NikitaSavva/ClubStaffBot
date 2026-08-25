from dataclasses import replace

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
    GetUserMenuContextQuery,
    MenuContext,
)
from application.identity.errors import UserHasNoRolesError, UserNotFoundError
from presentation.telegram.keyboards.role import RoleReplyKeyboardBuilder
from presentation.telegram.navigation import (
    NavigationAction,
    NavigationCallback,
    NavigationTarget,
)
from presentation.telegram.presenters import (
    RolePanel,
    RolePanelCallback,
    available_role_panels,
    build_role_panel_screen,
    build_role_selector_screen,
)
from presentation.telegram.screen import (
    BannerContext,
    TelegramScreen,
    TelegramScreenRenderer,
)
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    clear_flow_context,
    get_navigation_context,
    set_navigation_context,
)

MENU_TEXT = "Выберите раздел:"
USER_NOT_REGISTERED_TEXT = (
    "Сначала зарегистрируйтесь по ссылке-приглашению на ресепшене."
)
MENU_UNAVAILABLE_TEXT = "Для вашей учетной записи пока нет доступного меню."

_role_reply_keyboard_builder = RoleReplyKeyboardBuilder()


@inject
async def handle_menu(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    await clear_flow_context(state)
    if telegram_user is None:
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=replace(
                _unregistered_screen(),
                role_reply_markup=ReplyKeyboardRemove(),
            ),
        )
        return

    await show_home_screen(
        chat_id=message.chat.id,
        telegram_id=telegram_user.id,
        state=state,
        interactor=interactor,
        renderer=renderer,
    )


async def show_home_screen(
    *,
    chat_id: int,
    telegram_id: int,
    state: FSMContext,
    interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None = None,
    notice: str | None = None,
) -> None:
    context = await load_menu_context(
        telegram_id=telegram_id,
        interactor=interactor,
    )
    if context is None:
        await set_navigation_context(
            state,
            NavigationContext(
                root_screen=RootScreen.ROLE_SELECTOR,
                active_role=None,
            ),
        )
        await renderer.render(
            state=state,
            chat_id=chat_id,
            screen=replace(
                _unregistered_screen(),
                role_reply_markup=ReplyKeyboardRemove(),
            ),
            editable_message=editable_message,
        )
        return
    if not context.items:
        await set_navigation_context(
            state,
            NavigationContext(
                root_screen=RootScreen.ROLE_SELECTOR,
                active_role=None,
            ),
        )
        await renderer.render(
            state=state,
            chat_id=chat_id,
            screen=replace(
                _menu_unavailable_screen(),
                role_reply_markup=ReplyKeyboardRemove(),
            ),
            editable_message=editable_message,
        )
        return

    roles = available_role_panels(context)
    if len(roles) == 1:
        await _render_role_panel(
            chat_id=chat_id,
            state=state,
            renderer=renderer,
            editable_message=editable_message,
            context=context,
            role=roles[0],
            notice=notice,
        )
        return

    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_SELECTOR,
            active_role=None,
        ),
    )
    screen = replace(
        build_role_selector_screen(context),
        role_reply_markup=ReplyKeyboardRemove(),
    )
    if notice:
        screen = replace(screen, text=f"{notice}\n\n{screen.text}")
    await renderer.render(
        state=state,
        chat_id=chat_id,
        screen=screen,
        editable_message=editable_message,
    )


async def show_role_panel(
    *,
    chat_id: int,
    telegram_id: int,
    role: RolePanel,
    state: FSMContext,
    interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None = None,
    notice: str | None = None,
) -> None:
    context = await load_menu_context(
        telegram_id=telegram_id,
        interactor=interactor,
    )
    if context is None or role not in available_role_panels(context):
        await show_home_screen(
            chat_id=chat_id,
            telegram_id=telegram_id,
            state=state,
            interactor=interactor,
            renderer=renderer,
            editable_message=editable_message,
            notice=notice,
        )
        return
    await _render_role_panel(
        chat_id=chat_id,
        state=state,
        renderer=renderer,
        editable_message=editable_message,
        context=context,
        role=role,
        notice=notice,
    )


async def show_active_role_panel(
    *,
    chat_id: int,
    telegram_id: int,
    state: FSMContext,
    interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None = None,
    notice: str | None = None,
) -> None:
    navigation = await get_navigation_context(state)
    try:
        role = (
            RolePanel(navigation.active_role)
            if navigation is not None and navigation.active_role is not None
            else None
        )
    except ValueError:
        role = None
    if role is None:
        await show_home_screen(
            chat_id=chat_id,
            telegram_id=telegram_id,
            state=state,
            interactor=interactor,
            renderer=renderer,
            editable_message=editable_message,
            notice=notice,
        )
        return
    await show_role_panel(
        chat_id=chat_id,
        telegram_id=telegram_id,
        role=role,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=editable_message,
        notice=notice,
    )


@inject
async def handle_select_role_panel(
    callback: CallbackQuery,
    callback_data: RolePanelCallback,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await clear_flow_context(state)
    await show_role_panel(
        chat_id=message.chat.id,
        telegram_id=callback.from_user.id,
        role=callback_data.role,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_back_to_role_selector(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await clear_flow_context(state)
    await show_home_screen(
        chat_id=message.chat.id,
        telegram_id=callback.from_user.id,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_back_to_role_panel(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return

    await clear_flow_context(state)
    await show_active_role_panel(
        chat_id=message.chat.id,
        telegram_id=callback.from_user.id,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=message,
    )


@inject
async def handle_legacy_back_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    await clear_flow_context(state)
    await show_home_screen(
        chat_id=message.chat.id,
        telegram_id=callback.from_user.id,
        state=state,
        interactor=interactor,
        renderer=renderer,
        editable_message=message,
    )


def create_menu_router() -> Router:
    router = Router(name=__name__)
    router.message.register(handle_menu, Command("menu"))
    router.callback_query.register(
        handle_select_role_panel,
        RolePanelCallback.filter(),
    )
    router.callback_query.register(
        handle_back_to_role_selector,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.ROLE_SELECTOR)
        ),
    )
    router.callback_query.register(
        handle_back_to_role_panel,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.ROLE_PANEL)
        ),
    )
    router.callback_query.register(
        handle_legacy_back_to_menu,
        NavigationCallback.filter(
            (F.action == NavigationAction.BACK)
            & (F.target == NavigationTarget.MENU)
        ),
    )
    return router


async def _render_role_panel(
    *,
    chat_id: int,
    state: FSMContext,
    renderer: TelegramScreenRenderer,
    editable_message: Message | None,
    context: MenuContext,
    role: RolePanel,
    notice: str | None,
) -> None:
    roles = available_role_panels(context)
    root_screen = (
        RootScreen.ROLE_SELECTOR if len(roles) > 1 else RootScreen.ROLE_PANEL
    )
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=root_screen,
            active_role=role.value,
        ),
    )
    await renderer.render(
        state=state,
        chat_id=chat_id,
        screen=replace(
            build_role_panel_screen(role, notice=notice),
            role_reply_markup=_role_reply_keyboard_builder.build(
                context,
                role,
                is_multi_role=len(roles) > 1,
            ),
        ),
        editable_message=editable_message,
    )


async def load_menu_context(
    *,
    telegram_id: int,
    interactor: GetUserMenuContextInteractor,
) -> MenuContext | None:
    try:
        return await interactor(
            GetUserMenuContextQuery(telegram_id=telegram_id)
        )
    except UserNotFoundError:
        return None
    except UserHasNoRolesError:
        return MenuContext(items=())


def _unregistered_screen() -> TelegramScreen:
    return TelegramScreen(
        text=USER_NOT_REGISTERED_TEXT,
        banner=BannerContext.ROLE_SELECTOR,
    )


def _menu_unavailable_screen() -> TelegramScreen:
    return TelegramScreen(
        text=MENU_UNAVAILABLE_TEXT,
        banner=BannerContext.ROLE_SELECTOR,
    )
