from hashlib import sha256
from uuid import UUID

import pytest
from itsdangerous import TimestampSigner

from application.athlete_qr import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)
from infrastructure.athlete_qr import (
    ATHLETE_QR_SIGNING_PURPOSE,
    ItsDangerousAthleteQrTokenCodec,
)

ATHLETE_PUBLIC_ID = UUID("12345678-1234-4678-9234-567812345678")
OTHER_ATHLETE_PUBLIC_ID = UUID("87654321-4321-4765-8765-432187654321")
SECRET = "s" * 32
OTHER_SECRET = "o" * 32
TTL_SECONDS = 300
ISSUED_AT = 1_756_713_600


@pytest.fixture
def controlled_timestamp(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    current = {"value": ISSUED_AT}
    monkeypatch.setattr(
        "itsdangerous.timed.time.time",
        lambda: current["value"],
    )
    return current


def codec(secret: str = SECRET) -> ItsDangerousAthleteQrTokenCodec:
    return ItsDangerousAthleteQrTokenCodec(
        secret=secret,
        ttl_seconds=TTL_SECONDS,
    )


def signer(*, secret: str = SECRET, purpose: str) -> TimestampSigner:
    return TimestampSigner(
        secret_key=secret,
        salt=purpose,
        digest_method=sha256,
    )


def test_issue_and_verify_round_trip_typed_athlete_public_id(
    controlled_timestamp: dict[str, int],
) -> None:
    token_codec = codec()

    token = token_codec.issue(ATHLETE_PUBLIC_ID)

    assert token_codec.verify(token) == ATHLETE_PUBLIC_ID
    assert isinstance(token_codec.verify(token), UUID)
    assert token.split(".", maxsplit=1)[0] == str(ATHLETE_PUBLIC_ID)
    assert len(token) == 87


def test_different_athletes_round_trip_to_their_own_identity(
    controlled_timestamp: dict[str, int],
) -> None:
    token_codec = codec()

    first = token_codec.issue(ATHLETE_PUBLIC_ID)
    second = token_codec.issue(OTHER_ATHLETE_PUBLIC_ID)

    assert token_codec.verify(first) == ATHLETE_PUBLIC_ID
    assert token_codec.verify(second) == OTHER_ATHLETE_PUBLIC_ID


def test_token_is_valid_at_exact_ttl_boundary(
    controlled_timestamp: dict[str, int],
) -> None:
    token_codec = codec()
    token = token_codec.issue(ATHLETE_PUBLIC_ID)
    controlled_timestamp["value"] = ISSUED_AT + TTL_SECONDS

    assert token_codec.verify(token) == ATHLETE_PUBLIC_ID


def test_token_is_expired_after_ttl_without_sleep(
    controlled_timestamp: dict[str, int],
) -> None:
    token_codec = codec()
    token = token_codec.issue(ATHLETE_PUBLIC_ID)
    controlled_timestamp["value"] = ISSUED_AT + TTL_SECONDS + 1

    with pytest.raises(AthleteQrTokenExpiredError):
        token_codec.verify(token)


def test_tampered_token_has_controlled_invalid_signature_error(
    controlled_timestamp: dict[str, int],
) -> None:
    token_codec = codec()
    token = token_codec.issue(ATHLETE_PUBLIC_ID)
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(AthleteQrTokenInvalidSignatureError):
        token_codec.verify(f"{token[:-1]}{replacement}")


def test_token_signed_with_other_secret_is_invalid(
    controlled_timestamp: dict[str, int],
) -> None:
    token = codec(secret=OTHER_SECRET).issue(ATHLETE_PUBLIC_ID)

    with pytest.raises(AthleteQrTokenInvalidSignatureError):
        codec().verify(token)


def test_token_signed_for_other_purpose_is_invalid(
    controlled_timestamp: dict[str, int],
) -> None:
    token = signer(secret=SECRET, purpose="other-purpose").sign(
        str(ATHLETE_PUBLIC_ID)
    )

    with pytest.raises(AthleteQrTokenInvalidSignatureError):
        codec().verify(token.decode("ascii"))


def test_valid_signature_with_malformed_uuid_has_controlled_payload_error(
    controlled_timestamp: dict[str, int],
) -> None:
    token = signer(
        secret=SECRET,
        purpose=ATHLETE_QR_SIGNING_PURPOSE,
    ).sign("not-an-athlete-public-id")

    with pytest.raises(AthleteQrTokenMalformedPayloadError):
        codec().verify(token.decode("ascii"))


def test_valid_signature_with_non_canonical_uuid_is_malformed(
    controlled_timestamp: dict[str, int],
) -> None:
    token = signer(
        secret=SECRET,
        purpose=ATHLETE_QR_SIGNING_PURPOSE,
    ).sign(str(ATHLETE_PUBLIC_ID).replace("-", ""))

    with pytest.raises(AthleteQrTokenMalformedPayloadError):
        codec().verify(token.decode("ascii"))
