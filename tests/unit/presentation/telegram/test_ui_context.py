from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from presentation.telegram.states import RoleManagementStates
from presentation.telegram.ui_context import (
    ActiveUiMessage,
    NavigationContext,
    RootScreen,
    UiMessageKind,
    clear_flow_context,
    get_active_ui_message,
    get_flow_context,
    get_navigation_context,
    set_active_ui_message,
    set_flow_context,
    set_navigation_context,
)


def make_state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=2, user_id=2),
    )


async def test_flow_cleanup_preserves_ui_context() -> None:
    state = make_state()
    active = ActiveUiMessage(
        chat_id=2,
        message_id=10,
        kind=UiMessageKind.MEDIA,
        media_key="banner:admin_panel",
        content_fingerprint="content",
        keyboard_fingerprint="keyboard",
    )
    navigation = NavigationContext(
        root_screen=RootScreen.ROLE_SELECTOR,
        active_role="administrator",
    )
    await set_active_ui_message(state, active)
    await set_navigation_context(state, navigation)
    await set_flow_context(
        state,
        {"search_query": "ivan", "target_user_id": 42},
    )
    await state.set_state(RoleManagementStates.viewing_user)

    await clear_flow_context(state)

    assert await state.get_state() is None
    assert await get_flow_context(state) == {}
    assert await get_active_ui_message(state) == active
    assert await get_navigation_context(state) == navigation
