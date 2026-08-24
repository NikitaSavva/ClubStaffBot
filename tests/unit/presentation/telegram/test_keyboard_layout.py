import pytest

from presentation.telegram.keyboards.layout import (
    build_callback_button,
    build_inline_keyboard,
    build_web_app_button,
)


def test_keyboard_preserves_explicit_layout_rows() -> None:
    primary = build_callback_button(text="Primary", callback_data="primary")
    related_a = build_callback_button(text="A", callback_data="related:a")
    related_b = build_callback_button(text="B", callback_data="related:b")
    previous = build_callback_button(text="←", callback_data="page:previous")
    counter = build_callback_button(text="2/10", callback_data="page:current")
    following = build_callback_button(text="→", callback_data="page:next")

    keyboard = build_inline_keyboard(
        (primary,),
        (related_a, related_b),
        (previous, counter, following),
    )

    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Primary"],
        ["A", "B"],
        ["←", "2/10", "→"],
    ]


def test_callback_payload_is_limited_to_telegram_size() -> None:
    with pytest.raises(ValueError):
        build_callback_button(text="Too large", callback_data="я" * 33)


def test_web_app_button_is_supported_without_product_configuration() -> None:
    button = build_web_app_button(
        text="WebApp",
        url="https://example.test/future-web-app",
    )

    assert button.callback_data is None
    assert button.web_app is not None
    assert button.web_app.url == "https://example.test/future-web-app"
