from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity import (
    GetUserMenuContextInteractor,
    GetUserMenuContextQuery,
    MenuContext,
)
from application.identity.errors import UserHasNoRolesError, UserNotFoundError
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
    RenderMode,
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

USER_NOT_REGISTERED_TEXT = (
    "Сначала зарегистрируйтесь по ссылке-приглашению на ресепшене."
)
MENU_UNAVAILABLE_TEXT = "Для вашей учетной записи пока нет доступного меню."


async def set_administrative_navigation_context(state: FSMContext) -> None:
    navigation = await get_navigation_context(state)
    active_role = (
        RolePanel.OWNER.value
        if navigation is not None
        and navigation.active_role == RolePanel.OWNER.value
        else RolePanel.ADMINISTRATOR.value
    )
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_PANEL,
            active_role=active_role,
        ),
    )


@inject
async def handle_menu(
    message: Message,
    state: FSMContext,
    interactor: FromDishka[GetUserMenuContextInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        await clear_flow_context(state)
        await renderer.render(
            state=state,
            chat_id=message.chat.id,
            screen=_unregistered_screen(),
            mode=RenderMode.NEW,
        )
        return

    await recover_home_screen(
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
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    context = await _load_menu_context(
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
            screen=_unregistered_screen(),
            mode=mode,
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
            screen=_menu_unavailable_screen(),
            mode=mode,
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
            mode=mode,
        )
        return

    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_SELECTOR,
            active_role=None,
        ),
    )
    screen = build_role_selector_screen(context)
    if notice:
        screen = TelegramScreen(
            text=f"{notice}\n\n{screen.text}",
            reply_markup=screen.reply_markup,
            banner=screen.banner,
        )
    await renderer.render(
        state=state,
        chat_id=chat_id,
        screen=screen,
        mode=mode,
        editable_message=editable_message,
    )


async def recover_home_screen(
    *,
    chat_id: int,
    telegram_id: int,
    state: FSMContext,
    interactor: GetUserMenuContextInteractor,
    renderer: TelegramScreenRenderer,
    notice: str | None = None,
) -> None:
    """Rebuild the root UI without trusting persisted Presentation state."""
    await clear_flow_context(state)
    await show_home_screen(
        chat_id=chat_id,
        telegram_id=telegram_id,
        state=state,
        interactor=interactor,
        renderer=renderer,
        notice=notice,
        mode=RenderMode.NEW,
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
    mode: RenderMode = RenderMode.EDIT,
) -> None:
    context = await _load_menu_context(
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
            mode=mode,
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
        mode=mode,
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
    mode: RenderMode = RenderMode.EDIT,
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
            mode=mode,
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
        mode=mode,
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
        mode=RenderMode.NEW,
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
        mode=RenderMode.NEW,
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
    mode: RenderMode = RenderMode.EDIT,
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
        screen=build_role_panel_screen(
            context,
            role,
            show_role_selector_back=len(roles) > 1,
            notice=notice,
        ),
        mode=mode,
        editable_message=editable_message,
    )


async def _load_menu_context(
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
