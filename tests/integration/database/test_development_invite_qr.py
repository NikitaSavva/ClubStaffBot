from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from sqlalchemy import select

from bootstrap.config import Settings
from bootstrap.container import create_container
from domain.identity import BotInvitePurpose
from infrastructure.database.models import BotInviteModel
from infrastructure.database.session import create_engine, create_session_factory
from infrastructure.security import Sha256InviteTokenHasher
from scripts import create_dev_invite


async def test_create_invite_qr_persists_only_hash_and_writes_correct_link(
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = create_container(integration_settings)
    output_path = tmp_path / "static" / "reception-invite.png"
    captured_links: list[str] = []
    real_generator = create_dev_invite.generate_qr_code

    def capture_link(deep_link: str, path: Path) -> Path:
        captured_links.append(deep_link)
        return real_generator(deep_link, path)

    monkeypatch.setattr(create_dev_invite, "generate_qr_code", capture_link)

    try:
        result = await create_dev_invite.create_invite_qr(
            container,
            "@club_test_bot",
            output_path,
        )
    finally:
        await container.close()

    parsed_link = urlparse(result.deep_link)
    raw_token = parse_qs(parsed_link.query)["start"][0]
    token_hash = Sha256InviteTokenHasher().hash(raw_token)

    engine = create_engine(integration_settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stored_invite = await session.scalar(
                select(BotInviteModel).where(
                    BotInviteModel.token_hash == token_hash
                )
            )
            raw_token_stored = await session.scalar(
                select(BotInviteModel.token_hash).where(
                    BotInviteModel.token_hash == raw_token
                )
            )
    finally:
        await engine.dispose()

    assert parsed_link.scheme == "https"
    assert parsed_link.netloc == "t.me"
    assert parsed_link.path == "/club_test_bot"
    assert stored_invite is not None
    assert stored_invite.token_hash == token_hash
    assert stored_invite.purpose is BotInvitePurpose.REGISTRATION
    assert stored_invite.athlete_id is None
    assert stored_invite.consumed_at is None
    assert raw_token_stored is None
    assert captured_links == [result.deep_link]
    assert result.qr_path == output_path
    with Image.open(output_path) as image:
        assert image.format == "PNG"
        image.verify()
