from dataclasses import dataclass
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

from application.identity import MenuContext
from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
)
from presentation.telegram.screen import BannerContext, TelegramScreen


class RolePanel(StrEnum):
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
    panel_title: str
    banner: BannerContext


_ROLE_PRESENTATIONS = (
    _RolePresentation(
        role=RolePanel.ADMINISTRATOR,
        home_action_id="administrator.home",
        selector_title="Администратор",
        panel_title="Панель администратора",
        banner=BannerContext.ADMIN_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.TRAINER,
        home_action_id="trainer.home",
        selector_title="Тренер",
        panel_title="Панель тренера",
        banner=BannerContext.TRAINER_PANEL,
    ),
    _RolePresentation(
        role=RolePanel.ATHLETE,
        home_action_id="athlete.home",
        selector_title="Спортсмен",
        panel_title="Панель спортсмена",
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
        text="Выберите раздел:",
        reply_markup=build_inline_keyboard(*rows),
        banner=BannerContext.ROLE_SELECTOR,
    )


def build_role_panel_screen(
    role: RolePanel,
    *,
    notice: str | None = None,
) -> TelegramScreen:
    presentation = _presentation_for(role)
    text = presentation.panel_title
    if notice:
        text = f"{notice}\n\n{text}"
    return TelegramScreen(
        text=text,
        banner=presentation.banner,
    )


def _presentation_for(role: RolePanel) -> _RolePresentation:
    return next(
        presentation
        for presentation in _ROLE_PRESENTATIONS
        if presentation.role is role
    )
