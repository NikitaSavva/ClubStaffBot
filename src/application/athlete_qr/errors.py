from application.errors import ApplicationError


class AthleteQrTokenExpiredError(ApplicationError):
    """The signed Athlete QR token is older than the configured TTL."""


class AthleteQrTokenInvalidSignatureError(ApplicationError):
    """The Athlete QR token signature or timestamp is invalid."""


class AthleteQrTokenMalformedPayloadError(ApplicationError):
    """The signed payload is not a valid Athlete public identifier."""
