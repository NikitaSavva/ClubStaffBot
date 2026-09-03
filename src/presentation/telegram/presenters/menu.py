from dataclasses import dataclass
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton

from application.identity import MenuContext, MenuItem
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
    build_web_app_button,
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
            "Меню владельца\n\nУправляйте спортсменами, Telegram-аккаунтами "
            "и ролями пользователей."
        ),
        banner=BannerContext.OWNER_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.ADMINISTRATOR,
        home_action_id="administrator.home",
        selector_title="Администратор",
        panel_caption=(
            "Меню администратора\n\nДобавляйте спортсменов, связывайте их с "
            "Telegram и управляйте ролями пользователей."
        ),
        banner=BannerContext.ADMIN_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.TRAINER,
        home_action_id="trainer.home",
        selector_title="Тренер",
        panel_caption="Просматривайте свое расписание тренировок.",
        banner=BannerContext.TRAINER_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.ATHLETE,
        home_action_id="athlete.home",
        selector_title="Спортсмен",
        panel_caption=(
            "Показывайте свой QR-код, просматривайте расписание и "
            "информацию об абонементе."
        ),
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
        scanner = items.get("administrator.scan_qr")
        if scanner is not None:
            rows.append((_menu_item_button(scanner),))
        confirm_attendance = items.get("administrator.confirm_attendance")
        if confirm_attendance is not None:
            rows.append((_menu_item_button(confirm_attendance),))
        schedule = items.get("administrator.schedule")
        if schedule is not None:
            rows.append((_menu_item_button(schedule),))
        activate_subscription = items.get(
            "administrator.activate_subscription"
        )
        if activate_subscription is not None:
            rows.append((_menu_item_button(activate_subscription),))
        view_subscription = items.get("administrator.view_subscription")
        if view_subscription is not None:
            rows.append((_menu_item_button(view_subscription),))
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
    if role is RolePanel.TRAINER:
        schedule = items.get("trainer.schedule")
        if schedule is not None:
            rows.append((_menu_item_button(schedule),))
    if role is RolePanel.ATHLETE:
        my_qr = items.get("athlete.my_qr")
        if my_qr is not None:
            rows.append((_menu_item_button(my_qr),))
        schedule = items.get("athlete.schedule")
        if schedule is not None:
            rows.append((_menu_item_button(schedule),))
        my_subscription = items.get("athlete.my_subscription")
        if my_subscription is not None:
            rows.append((_menu_item_button(my_subscription),))
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
    if item.web_app_url is not None:
        return build_web_app_button(text=item.title, url=item.web_app_url)
    return build_callback_button(
        text=item.title,
        callback_data=item.action_id,
    )
