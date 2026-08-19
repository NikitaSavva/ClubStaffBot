import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import qrcode
from dishka import AsyncContainer
from qrcode.image.pil import PilImage

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.development import create_development_invite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QR_PATH = PROJECT_ROOT / "static" / "reception-invite.png"


@dataclass(frozen=True, slots=True)
class DevelopmentInviteQrResult:
    deep_link: str
    qr_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a development-only reception BotInvite.",
    )
    parser.add_argument(
        "--bot-username",
        required=True,
        help="Telegram bot username used in the reception deep link.",
    )
    return parser


def normalize_bot_username(bot_username: str) -> str:
    normalized_username = bot_username.removeprefix("@").strip()
    if not normalized_username:
        raise ValueError("Telegram bot username must not be empty")
    return normalized_username


def build_deep_link(raw_token: str, bot_username: str) -> str:
    normalized_username = normalize_bot_username(bot_username)
    encoded_username = quote(normalized_username, safe="")
    encoded_token = quote(raw_token, safe="")
    return f"https://t.me/{encoded_username}?start={encoded_token}"


def generate_qr_code(deep_link: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    qr_code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr_code.add_data(deep_link)
    qr_code.make(fit=True)
    image = qr_code.make_image(
        image_factory=PilImage,
        fill_color="black",
        back_color="white",
    )
    try:
        image.save(temporary_path, format="PNG")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


async def create_invite_qr(
    container: AsyncContainer,
    bot_username: str,
    output_path: Path = DEFAULT_QR_PATH,
) -> DevelopmentInviteQrResult:
    normalized_username = normalize_bot_username(bot_username)
    raw_token = await create_development_invite(container)
    deep_link = build_deep_link(raw_token, normalized_username)
    qr_path = generate_qr_code(deep_link, output_path)
    return DevelopmentInviteQrResult(deep_link=deep_link, qr_path=qr_path)


async def run(
    bot_username: str,
    output_path: Path = DEFAULT_QR_PATH,
) -> DevelopmentInviteQrResult:
    # BaseSettings loads the required application configuration from environment.
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        return await create_invite_qr(container, bot_username, output_path)
    finally:
        await container.close()


def main() -> None:
    args = build_parser().parse_args()
    result = asyncio.run(run(args.bot_username))
    print(f"Deep link: {result.deep_link}")
    print(f"QR code: {result.qr_path}")


if __name__ == "__main__":
    main()
