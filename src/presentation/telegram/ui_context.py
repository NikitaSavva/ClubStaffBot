from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from aiogram.fsm.context import FSMContext

FLOW_CONTEXT_KEY = "flow_context"
UI_CONTEXT_KEY = "ui_context"

_ACTIVE_MESSAGE_KEY = "active_message"
_NAVIGATION_KEY = "navigation"
_ROLE_REPLY_KEYBOARD_FINGERPRINT_KEY = "role_reply_keyboard_fingerprint"


class UiMessageKind(StrEnum):
    TEXT = "text"
    MEDIA = "media"


class RootScreen(StrEnum):
    ROLE_SELECTOR = "role_selector"
    ROLE_PANEL = "role_panel"


@dataclass(frozen=True, slots=True)
class ActiveUiMessage:
    chat_id: int
    message_id: int
    kind: UiMessageKind
    media_key: str | None
    content_fingerprint: str
    keyboard_fingerprint: str


@dataclass(frozen=True, slots=True)
class NavigationContext:
    root_screen: RootScreen
    active_role: str | None


async def get_flow_context(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    return _as_dict(data.get(FLOW_CONTEXT_KEY))


async def set_flow_context(
    state: FSMContext,
    flow_context: Mapping[str, Any],
) -> None:
    data = await state.get_data()
    data[FLOW_CONTEXT_KEY] = dict(flow_context)
    await state.set_data(data)


async def update_flow_context(
    state: FSMContext,
    **values: Any,
) -> None:
    flow_context = await get_flow_context(state)
    flow_context.update(values)
    await set_flow_context(state, flow_context)


async def clear_flow_context(state: FSMContext) -> None:
    data = await state.get_data()
    ui_context = _as_dict(data.get(UI_CONTEXT_KEY))
    await state.set_state(None)
    await state.set_data(
        {UI_CONTEXT_KEY: ui_context} if ui_context else {}
    )


async def get_active_ui_message(
    state: FSMContext,
) -> ActiveUiMessage | None:
    ui_context = await _get_ui_context(state)
    raw_message = ui_context.get(_ACTIVE_MESSAGE_KEY)
    if not isinstance(raw_message, Mapping):
        return None
    try:
        return ActiveUiMessage(
            chat_id=int(raw_message["chat_id"]),
            message_id=int(raw_message["message_id"]),
            kind=UiMessageKind(str(raw_message["kind"])),
            media_key=_optional_str(raw_message.get("media_key")),
            content_fingerprint=str(raw_message["content_fingerprint"]),
            keyboard_fingerprint=str(raw_message["keyboard_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def set_active_ui_message(
    state: FSMContext,
    message: ActiveUiMessage,
) -> None:
    data = await state.get_data()
    ui_context = _as_dict(data.get(UI_CONTEXT_KEY))
    ui_context[_ACTIVE_MESSAGE_KEY] = asdict(message)
    data[UI_CONTEXT_KEY] = ui_context
    await state.set_data(data)


async def get_navigation_context(
    state: FSMContext,
) -> NavigationContext | None:
    ui_context = await _get_ui_context(state)
    raw_navigation = ui_context.get(_NAVIGATION_KEY)
    if not isinstance(raw_navigation, Mapping):
        return None
    try:
        return NavigationContext(
            root_screen=RootScreen(str(raw_navigation["root_screen"])),
            active_role=_optional_str(raw_navigation.get("active_role")),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def set_navigation_context(
    state: FSMContext,
    navigation: NavigationContext,
) -> None:
    data = await state.get_data()
    ui_context = _as_dict(data.get(UI_CONTEXT_KEY))
    ui_context[_NAVIGATION_KEY] = asdict(navigation)
    data[UI_CONTEXT_KEY] = ui_context
    await state.set_data(data)


async def get_role_reply_keyboard_fingerprint(
    state: FSMContext,
) -> str | None:
    ui_context = await _get_ui_context(state)
    return _optional_str(
        ui_context.get(_ROLE_REPLY_KEYBOARD_FINGERPRINT_KEY)
    )


async def set_role_reply_keyboard_fingerprint(
    state: FSMContext,
    fingerprint: str,
) -> None:
    data = await state.get_data()
    ui_context = _as_dict(data.get(UI_CONTEXT_KEY))
    ui_context[_ROLE_REPLY_KEYBOARD_FINGERPRINT_KEY] = fingerprint
    data[UI_CONTEXT_KEY] = ui_context
    await state.set_data(data)


async def _get_ui_context(state: FSMContext) -> dict[str, Any]:
    data = await state.get_data()
    return _as_dict(data.get(UI_CONTEXT_KEY))


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
