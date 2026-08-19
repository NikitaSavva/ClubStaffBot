from datetime import UTC, datetime, timedelta

import pytest

from domain.identity import BotInvite

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def make_invite(
    *,
    is_active: bool = True,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> BotInvite:
    return BotInvite(
        id=1,
        token_hash="hash",
        is_active=is_active,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def test_active_non_expiring_invite_is_valid() -> None:
    assert make_invite().is_valid(NOW)


@pytest.mark.parametrize(
    "invite",
    [
        make_invite(is_active=False),
        make_invite(expires_at=NOW),
        make_invite(expires_at=NOW - timedelta(seconds=1)),
        make_invite(revoked_at=NOW - timedelta(seconds=1)),
    ],
)
def test_unavailable_invite_is_invalid(invite: BotInvite) -> None:
    assert not invite.is_valid(NOW)


def test_future_expiration_is_valid() -> None:
    assert make_invite(expires_at=NOW + timedelta(seconds=1)).is_valid(NOW)
