from aiogram.types import BufferedInputFile

from presentation.telegram.navigation import (
    build_menu_button,
    build_single_button_keyboard,
)
from presentation.telegram.screen import (
    BannerContext,
    TelegramScreen,
)

TITLE = "Мой QR"
BODY = "Покажите QR-код администратору клуба при посещении."
ATHLETE_PROFILE_NOT_FOUND_TEXT = (
    "Профиль спортсмена не найден. Обратитесь к администратору."
)
ATHLETE_PERMISSION_DENIED_TEXT = "Действие доступно только спортсмену."


def build_my_qr_screen(qr_png: bytes) -> TelegramScreen:
    return TelegramScreen(
        text=f"{TITLE}\n\n{BODY}",
        reply_markup=build_single_button_keyboard(build_menu_button()),
        media=BufferedInputFile(qr_png, filename="athlete-qr.png"),
        media_key="athlete-my-qr",
    )


def build_athlete_profile_not_found_screen() -> TelegramScreen:
    return _error_screen(ATHLETE_PROFILE_NOT_FOUND_TEXT)


def build_athlete_permission_denied_screen() -> TelegramScreen:
    return _error_screen(ATHLETE_PERMISSION_DENIED_TEXT)


def _error_screen(message: str) -> TelegramScreen:
    return TelegramScreen(
        text=f"{TITLE}\n\n{message}",
        reply_markup=build_single_button_keyboard(build_menu_button()),
        banner=BannerContext.ATHLETE_PANEL,
    )
