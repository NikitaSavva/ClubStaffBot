from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import Chat, Message, PhotoSize

from scripts.upload_telegram_banners import (
    BannerPaths,
    build_parser,
    select_reusable_file_id,
    upload_banners,
    validate_banner_paths,
)


def test_parser_requires_explicit_chat_id() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            [
                "--admin-panel",
                "admin.png",
                "--owner-panel",
                "owner.png",
                "--trainer-panel",
                "trainer.png",
                "--athlete-panel",
                "athlete.png",
                "--role-selector",
                "selector.png",
            ]
        )

    assert error.value.code == 2


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
        owner_panel=tmp_path / "owner.png",
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
        owner_panel=tmp_path / "owner.png",
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
        make_message(make_photo("owner-id", 1280, 720)),
        make_message(make_photo("trainer-id", 1280, 720)),
        make_message(make_photo("athlete-id", 1280, 720)),
        make_message(make_photo("selector-id", 1280, 720)),
    ]

    result = await upload_banners(cast(Bot, sender), 123, paths)

    assert result == {
        "ADMIN_PANEL_BANNER_FILE_ID": "admin-id",
        "OWNER_PANEL_BANNER_FILE_ID": "owner-id",
        "TRAINER_PANEL_BANNER_FILE_ID": "trainer-id",
        "ATHLETE_PANEL_BANNER_FILE_ID": "athlete-id",
        "ROLE_SELECTOR_BANNER_FILE_ID": "selector-id",
    }
    assert sender.send_photo.await_count == 5
    for call, (_, caption, path) in zip(
        sender.send_photo.await_args_list,
        paths.uploads(),
        strict=True,
    ):
        assert call.kwargs["chat_id"] == 123
        assert call.kwargs["caption"] == caption
        assert call.kwargs["photo"].path == path


async def test_upload_banners_skips_existing_file_ids_on_repeat_run(
    tmp_path: Path,
) -> None:
    paths = BannerPaths(
        admin_panel=tmp_path / "missing-admin.png",
        owner_panel=tmp_path / "missing-owner.png",
        trainer_panel=tmp_path / "missing-trainer.png",
        athlete_panel=tmp_path / "missing-athlete.png",
        role_selector=tmp_path / "missing-role-selector.png",
    )
    existing_file_ids = {
        env_name: f"existing-{env_name.lower()}"
        for env_name, _, _ in paths.uploads()
    }
    sender = AsyncMock(spec=Bot)

    result = await upload_banners(
        cast(Bot, sender),
        123,
        paths,
        existing_file_ids=existing_file_ids,
    )

    assert result == existing_file_ids
    sender.send_photo.assert_not_awaited()


async def test_upload_banners_uploads_only_missing_owner_banner(
    tmp_path: Path,
) -> None:
    paths = BannerPaths(
        admin_panel=tmp_path / "missing-admin.png",
        owner_panel=tmp_path / "owner.png",
        trainer_panel=tmp_path / "missing-trainer.png",
        athlete_panel=tmp_path / "missing-athlete.png",
        role_selector=tmp_path / "missing-role-selector.png",
    )
    paths.owner_panel.touch()
    existing_file_ids = {
        "ADMIN_PANEL_BANNER_FILE_ID": "admin-id",
        "TRAINER_PANEL_BANNER_FILE_ID": "trainer-id",
        "ATHLETE_PANEL_BANNER_FILE_ID": "athlete-id",
        "ROLE_SELECTOR_BANNER_FILE_ID": "selector-id",
    }
    sender = AsyncMock(spec=Bot)
    sender.send_photo.return_value = make_message(
        make_photo("owner-id", 1280, 720)
    )

    result = await upload_banners(
        cast(Bot, sender),
        123,
        paths,
        existing_file_ids=existing_file_ids,
    )

    assert result == {
        "ADMIN_PANEL_BANNER_FILE_ID": "admin-id",
        "OWNER_PANEL_BANNER_FILE_ID": "owner-id",
        "TRAINER_PANEL_BANNER_FILE_ID": "trainer-id",
        "ATHLETE_PANEL_BANNER_FILE_ID": "athlete-id",
        "ROLE_SELECTOR_BANNER_FILE_ID": "selector-id",
    }
    sender.send_photo.assert_awaited_once()
    assert sender.send_photo.await_args.kwargs["caption"] == "Owner panel banner"
    assert sender.send_photo.await_args.kwargs["photo"].path == paths.owner_panel
