from dataclasses import dataclass
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from application.identity import MenuContext, MenuItem
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.navigation import (
    NavigationTarget,
    build_back_button,
)
from presentation.telegram.screen import BannerContext, TelegramScreen


class RolePanel(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    TRAINER = "trainer"
    ATHLETE = "athlete"


class RolePanelCallback(CallbackData, prefix="role_panel"):
    role: RolePanel


@dataclass(frozen=True, slots=True)
class _RolePresentation:
    role: RolePanel
    home_action_id: str
    selector_title: str
    panel_caption: str
    banner: BannerContext


_ROLE_PRESENTATIONS = (
    _RolePresentation(
        role=RolePanel.OWNER,
        home_action_id="owner.home",
        selector_title="Владелец",
        panel_caption=(
            "Управляйте спортсменами, Telegram-аккаунтами и ролями "
            "пользователей."
        ),
        banner=BannerContext.ADMIN_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.ADMINISTRATOR,
        home_action_id="administrator.home",
        selector_title="Администратор",
        panel_caption=(
            "Добавляйте спортсменов, связывайте их с Telegram и управляйте "
            "ролями пользователей."
        ),
        banner=BannerContext.ADMIN_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.TRAINER,
        home_action_id="trainer.home",
        selector_title="Тренер",
        panel_caption="Для тренера пока нет доступных действий.",
        banner=BannerContext.TRAINER_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.ATHLETE,
        home_action_id="athlete.home",
        selector_title="Спортсмен",
        panel_caption="Для спортсмена пока нет доступных действий.",
        banner=BannerContext.ATHLETE_PANEL,
    ),
)


def available_role_panels(context: MenuContext) -> tuple[RolePanel, ...]:
    action_ids = {item.action_id for item in context.items}
    return tuple(
        presentation.role
        for presentation in _ROLE_PRESENTATIONS
        if presentation.home_action_id in action_ids
    )


def build_role_selector_screen(context: MenuContext) -> TelegramScreen:
    available = set(available_role_panels(context))
    buttons = [
        build_callback_button(
            text=presentation.selector_title,
            callback_data=RolePanelCallback(role=presentation.role).pack(),
        )
        for presentation in _ROLE_PRESENTATIONS
        if presentation.role in available
    ]
    rows = tuple(tuple(buttons[index : index + 2]) for index in range(0, len(buttons), 2))
    return TelegramScreen(
        text="Выберите роль, в которой хотите продолжить работу.",
        reply_markup=build_inline_keyboard(*rows),
        banner=BannerContext.ROLE_SELECTOR,
    )


def build_role_panel_screen(
    context: MenuContext,
    role: RolePanel,
    *,
    show_role_selector_back: bool,
    notice: str | None = None,
) -> TelegramScreen:
    presentation = _presentation_for(role)
    action_prefixes = (
        ("owner.", "administrator.")
        if role is RolePanel.OWNER
        else (f"{role.value}.",)
    )
    items = {
        item.action_id: item
        for item in context.items
        if item.action_id.startswith(action_prefixes)
    }
    rows: list[tuple[InlineKeyboardButton, ...]] = []
    if role in (RolePanel.OWNER, RolePanel.ADMINISTRATOR):
        primary = items.get("administrator.create_athlete")
        if primary is not None:
            rows.append((_menu_item_button(primary),))
        assign_trainer = items.get("administrator.assign_trainer")
        if assign_trainer is not None:
            rows.append((_menu_item_button(assign_trainer),))
        related = tuple(
            _menu_item_button(item)
            for action_id in (
                "administrator.manage_users",
                "administrator.link_athlete_account",
            )
            if (item := items.get(action_id)) is not None
        )
        if related:
            rows.append(related)
    if show_role_selector_back:
        rows.append((build_back_button(NavigationTarget.ROLE_SELECTOR),))

    text = presentation.panel_caption
    if notice:
        text = f"{notice}\n\n{text}"
    return TelegramScreen(
        text=text,
        reply_markup=build_inline_keyboard(*rows),
        banner=presentation.banner,
    )


def _presentation_for(role: RolePanel) -> _RolePresentation:
    return next(
        presentation
        for presentation in _ROLE_PRESENTATIONS
        if presentation.role is role
    )


def _menu_item_button(item: MenuItem) -> InlineKeyboardButton:
    return build_callback_button(
        text=item.title,
        callback_data=item.action_id,
    )
