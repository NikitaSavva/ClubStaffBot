from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import Chat, Message, PhotoSize

from entrypoints.upload_telegram_banners import (
    BannerPaths,
    select_reusable_file_id,
    upload_banners,
    validate_banner_paths,
)


def make_message(*photos: PhotoSize) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=123, type=ChatType.PRIVATE),
        photo=list(photos),
    )


def make_photo(file_id: str, width: int, height: int) -> PhotoSize:
    return PhotoSize(
        file_id=file_id,
        file_unique_id=f"unique-{file_id}",
        width=width,
        height=height,
    )


def make_banner_paths(tmp_path: Path) -> BannerPaths:
    paths = BannerPaths(
        admin_panel=tmp_path / "admin.png",
        trainer_panel=tmp_path / "trainer.png",
        athlete_panel=tmp_path / "athlete.png",
        role_selector=tmp_path / "role-selector.png",
    )
    for _, _, path in paths.uploads():
        path.touch()
    return paths


def test_validate_banner_paths_reports_all_missing_files(tmp_path: Path) -> None:
    paths = BannerPaths(
        admin_panel=tmp_path / "admin.png",
        trainer_panel=tmp_path / "trainer.png",
        athlete_panel=tmp_path / "athlete.png",
        role_selector=tmp_path / "role-selector.png",
    )

    with pytest.raises(FileNotFoundError) as error:
        validate_banner_paths(paths)

    for _, _, path in paths.uploads():
        assert str(path) in str(error.value)


def test_select_reusable_file_id_selects_largest_photo() -> None:
    message = make_message(
        make_photo("small", width=90, height=90),
        make_photo("large", width=1280, height=720),
        make_photo("medium", width=640, height=480),
    )

    assert select_reusable_file_id(message) == "large"


def test_select_reusable_file_id_rejects_message_without_photo() -> None:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=123, type=ChatType.PRIVATE),
    )

    with pytest.raises(RuntimeError, match="does not contain"):
        select_reusable_file_id(message)


async def test_upload_banners_uploads_all_files_and_returns_env_values(
    tmp_path: Path,
) -> None:
    paths = make_banner_paths(tmp_path)
    sender = AsyncMock(spec=Bot)
    sender.send_photo.side_effect = [
        make_message(make_photo("admin-id", 1280, 720)),
        make_message(make_photo("trainer-id", 1280, 720)),
        make_message(make_photo("athlete-id", 1280, 720)),
        make_message(make_photo("selector-id", 1280, 720)),
    ]

    result = await upload_banners(cast(Bot, sender), 123, paths)

    assert result == {
        "ADMIN_PANEL_BANNER_FILE_ID": "admin-id",
        "TRAINER_PANEL_BANNER_FILE_ID": "trainer-id",
        "ATHLETE_PANEL_BANNER_FILE_ID": "athlete-id",
        "ROLE_SELECTOR_BANNER_FILE_ID": "selector-id",
    }
    assert sender.send_photo.await_count == 4
    for call, (_, caption, path) in zip(
        sender.send_photo.await_args_list,
        paths.uploads(),
        strict=True,
    ):
        assert call.kwargs["chat_id"] == 123
        assert call.kwargs["caption"] == caption
        assert call.kwargs["photo"].path == path
