from io import BytesIO
from urllib.parse import quote

import qrcode
from qrcode.image.pil import PilImage


def build_bot_start_deep_link(raw_token: str, bot_username: str) -> str:
    normalized_username = bot_username.removeprefix("@").strip()
    if not normalized_username:
        raise ValueError("Telegram bot username must not be empty")
    return (
        f"https://t.me/{quote(normalized_username, safe='')}"
        f"?start={quote(raw_token, safe='')}"
    )


def generate_qr_png(content: str) -> bytes:
    qr_code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr_code.add_data(content)
    qr_code.make(fit=True)
    image = qr_code.make_image(
        image_factory=PilImage,
        fill_color="black",
        back_color="white",
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
