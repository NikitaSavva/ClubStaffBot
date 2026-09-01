from io import BytesIO

from aiogram.types import BufferedInputFile
from PIL import Image

from presentation.telegram.navigation import MENU_BUTTON_TEXT
from presentation.telegram.presenters.athlete_qr import (
    ATHLETE_PERMISSION_DENIED_TEXT,
    ATHLETE_PROFILE_NOT_FOUND_TEXT,
    BODY,
    TITLE,
    build_athlete_permission_denied_screen,
    build_athlete_profile_not_found_screen,
    build_my_qr_screen,
)
from presentation.telegram.qr import generate_qr_png
from presentation.telegram.screen import BannerContext, TelegramScreen

SIGNED_TOKEN = (
    "12345678-1234-4678-9234-567812345678.abc123."
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNO12"
)


def button_text(screen: TelegramScreen) -> str:
    reply_markup = screen.reply_markup
    assert reply_markup is not None
    return reply_markup.inline_keyboard[0][0].text


def test_qr_helper_generates_in_memory_png_for_signed_token() -> None:
    qr_png = generate_qr_png(SIGNED_TOKEN)

    image = Image.open(BytesIO(qr_png))
    assert image.format == "PNG"
    assert image.size == (450, 450)
    assert qr_png


def test_my_qr_screen_contains_media_without_raw_identity_or_token() -> None:
    qr_png = generate_qr_png(SIGNED_TOKEN)

    screen = build_my_qr_screen(qr_png)

    assert screen.text == f"{TITLE}\n\n{BODY}"
    assert SIGNED_TOKEN not in screen.text
    assert SIGNED_TOKEN.split(".", maxsplit=1)[0] not in screen.text
    assert isinstance(screen.media, BufferedInputFile)
    assert screen.media.data == qr_png
    assert screen.media.filename == "athlete-qr.png"
    assert screen.media_key == "athlete-my-qr"
    assert button_text(screen) == MENU_BUTTON_TEXT


def test_missing_profile_screen_is_controlled() -> None:
    screen = build_athlete_profile_not_found_screen()

    assert screen.text == f"{TITLE}\n\n{ATHLETE_PROFILE_NOT_FOUND_TEXT}"
    assert screen.banner is BannerContext.ATHLETE_PANEL
    assert button_text(screen) == MENU_BUTTON_TEXT


def test_permission_denied_screen_is_controlled() -> None:
    screen = build_athlete_permission_denied_screen()

    assert screen.text == f"{TITLE}\n\n{ATHLETE_PERMISSION_DENIED_TEXT}"
    assert screen.banner is BannerContext.ATHLETE_PANEL
    assert button_text(screen) == MENU_BUTTON_TEXT
