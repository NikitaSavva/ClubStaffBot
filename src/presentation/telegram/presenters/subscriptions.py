from application.subscriptions import (
    GetMySubscriptionResult,
    MySubscriptionGroup,
)
from domain.subscriptions import SubscriptionAccessScope
from presentation.telegram.navigation import (
    build_menu_button,
    build_single_button_keyboard,
)
from presentation.telegram.screen import BannerContext, TelegramScreen

TITLE = "Мой абонемент"
NO_ACTIVE_SUBSCRIPTION_TEXT = "У вас нет активного абонемента."
ATHLETE_PROFILE_NOT_FOUND_TEXT = (
    "Профиль спортсмена не найден. Обратитесь к администратору."
)
ATHLETE_PERMISSION_DENIED_TEXT = "Действие доступно только спортсмену."


def build_my_subscription_screen(
    result: GetMySubscriptionResult,
) -> TelegramScreen:
    current = result.current
    if current is None:
        text = f"{TITLE}\n\n{NO_ACTIVE_SUBSCRIPTION_TEXT}"
    else:
        access = _format_access(current.access_scope, current.group)
        visits = (
            "Посещения:\nБез ограничений"
            if current.is_unlimited
            else f"Осталось посещений:\n{current.remaining_visits}"
        )
        text = (
            f"{TITLE}\n\n"
            f"Тариф:\n{current.plan_name}\n\n"
            f"{access}\n\n"
            f"Действует:\n{current.starts_at:%d.%m.%Y} – "
            f"{current.expires_at:%d.%m.%Y}\n\n"
            f"{visits}"
        )
    return _athlete_screen(text)


def build_athlete_profile_not_found_screen() -> TelegramScreen:
    return _athlete_screen(f"{TITLE}\n\n{ATHLETE_PROFILE_NOT_FOUND_TEXT}")


def build_athlete_permission_denied_screen() -> TelegramScreen:
    return _athlete_screen(f"{TITLE}\n\n{ATHLETE_PERMISSION_DENIED_TEXT}")


def format_my_subscription_group(group: MySubscriptionGroup) -> str:
    return f"{group.direction_name} · {group.group_name}"


def _format_access(
    access_scope: SubscriptionAccessScope,
    group: MySubscriptionGroup | None,
) -> str:
    if access_scope is SubscriptionAccessScope.ALL_REGULAR_GROUPS:
        return (
            "Доступ:\nВсе обычные группы клуба\n\n"
            "Мини-группы:\nНе входят"
        )
    if group is None:
        return "Группа:\nДанные группы недоступны"
    return f"Группа:\n{format_my_subscription_group(group)}"


def _athlete_screen(text: str) -> TelegramScreen:
    return TelegramScreen(
        text=text,
        reply_markup=build_single_button_keyboard(build_menu_button()),
        banner=BannerContext.ATHLETE_PANEL,
    )
