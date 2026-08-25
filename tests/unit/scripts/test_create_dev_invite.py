from pathlib import Path

import pytest
from PIL import Image

from scripts.create_dev_invite import build_deep_link, generate_qr_code


def test_build_deep_link_normalizes_username_and_encodes_token() -> None:
    assert build_deep_link("raw/token?", "@club_test_bot") == (
        "https://t.me/club_test_bot?start=raw%2Ftoken%3F"
    )


def test_build_deep_link_rejects_empty_username() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        build_deep_link("raw-token", "@")


def test_generate_qr_code_creates_png_and_parent_directory(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "static" / "reception-invite.png"

    result = generate_qr_code(
        "https://t.me/club_test_bot?start=raw-token",
        output_path,
    )

    assert result == output_path
    assert output_path.is_file()
    with Image.open(output_path) as image:
        assert image.format == "PNG"
        image.verify()
