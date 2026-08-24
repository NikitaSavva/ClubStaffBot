import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from bootstrap.config import Settings


class PhotoSender(Protocol):
    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: FSInputFile,
        caption: str,
    ) -> Message: ...


@dataclass(frozen=True, slots=True)
class BannerPaths:
    admin_panel: Path
    trainer_panel: Path
    athlete_panel: Path
    role_selector: Path

    def uploads(self) -> Sequence[tuple[str, str, Path]]:
        return (
            (
                "ADMIN_PANEL_BANNER_FILE_ID",
                "Administrator panel banner",
                self.admin_panel,
            ),
            (
                "TRAINER_PANEL_BANNER_FILE_ID",
                "Trainer panel banner",
                self.trainer_panel,
            ),
            (
                "ATHLETE_PANEL_BANNER_FILE_ID",
                "Athlete panel banner",
                self.athlete_panel,
            ),
            (
                "ROLE_SELECTOR_BANNER_FILE_ID",
                "Role selector banner",
                self.role_selector,
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Upload Telegram UI banners once and print deployment environment "
            "variables with their reusable file_ids."
        ),
        epilog=(
            "The target user must start a private chat with the bot before upload."
        ),
    )
    parser.add_argument(
        "--admin-panel",
        required=True,
        type=Path,
        help="Path to the administrator panel banner.",
    )
    parser.add_argument(
        "--trainer-panel",
        required=True,
        type=Path,
        help="Path to the trainer panel banner.",
    )
    parser.add_argument(
        "--athlete-panel",
        required=True,
        type=Path,
        help="Path to the athlete panel banner.",
    )
    parser.add_argument(
        "--role-selector",
        required=True,
        type=Path,
        help="Path to the neutral role selector banner.",
    )
    parser.add_argument(
        "--chat-id",
        type=int,
        help="Upload target chat ID. Defaults to TELEGRAM_OWNER_ID.",
    )
    return parser


def validate_banner_paths(paths: BannerPaths) -> None:
    missing_paths = [path for _, _, path in paths.uploads() if not path.is_file()]
    if missing_paths:
        formatted_paths = ", ".join(str(path) for path in missing_paths)
        raise FileNotFoundError(f"Banner file not found: {formatted_paths}")


def select_reusable_file_id(message: Message) -> str:
    if not message.photo:
        raise RuntimeError("Telegram response does not contain an uploaded photo")

    largest_photo = max(
        message.photo,
        key=lambda photo: (photo.width * photo.height, photo.file_size or 0),
    )
    return largest_photo.file_id


async def upload_banners(
    sender: PhotoSender,
    chat_id: int,
    paths: BannerPaths,
) -> dict[str, str]:
    validate_banner_paths(paths)
    file_ids: dict[str, str] = {}

    for env_name, caption, path in paths.uploads():
        message = await sender.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(path),
            caption=caption,
        )
        file_ids[env_name] = select_reusable_file_id(message)

    return file_ids


async def run(
    paths: BannerPaths,
    chat_id: int | None = None,
) -> dict[str, str]:
    # BaseSettings loads the required application configuration from environment.
    settings = Settings()  # type: ignore[call-arg]
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    try:
        return await upload_banners(
            bot,
            settings.telegram_owner_id if chat_id is None else chat_id,
            paths,
        )
    finally:
        await bot.session.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    paths = BannerPaths(
        admin_panel=args.admin_panel,
        trainer_panel=args.trainer_panel,
        athlete_panel=args.athlete_panel,
        role_selector=args.role_selector,
    )

    try:
        file_ids = asyncio.run(run(paths, args.chat_id))
    except FileNotFoundError as error:
        parser.error(str(error))

    for env_name, file_id in file_ids.items():
        print(f"{env_name}={file_id}")


if __name__ == "__main__":
    main()
