from hashlib import sha256
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from application.athlete_qr.errors import (
    AthleteQrTokenExpiredError,
    AthleteQrTokenInvalidSignatureError,
    AthleteQrTokenMalformedPayloadError,
)

ATHLETE_QR_SIGNING_PURPOSE = "athlete-qr"


class ItsDangerousAthleteQrTokenCodec:
    def __init__(self, *, secret: str, ttl_seconds: int) -> None:
        self._signer = TimestampSigner(
            secret_key=secret,
            salt=ATHLETE_QR_SIGNING_PURPOSE,
            digest_method=sha256,
        )
        self._ttl_seconds = ttl_seconds

    def issue(self, athlete_public_id: UUID) -> str:
        signed = self._signer.sign(str(athlete_public_id))
        return signed.decode("ascii")

    def verify(self, token: str) -> UUID:
        try:
            payload = self._signer.unsign(
                token,
                max_age=self._ttl_seconds,
            )
        except SignatureExpired as error:
            raise AthleteQrTokenExpiredError from error
        except BadSignature as error:
            raise AthleteQrTokenInvalidSignatureError from error

        try:
            encoded_public_id = payload.decode("ascii")
            athlete_public_id = UUID(encoded_public_id)
        except (UnicodeDecodeError, ValueError) as error:
            raise AthleteQrTokenMalformedPayloadError from error
        if encoded_public_id != str(athlete_public_id):
            raise AthleteQrTokenMalformedPayloadError
        return athlete_public_id
