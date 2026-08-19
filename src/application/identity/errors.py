from application.errors import ApplicationError


class InvalidBotInviteError(ApplicationError):
    """The supplied reception invite cannot authorize registration."""


class UserAlreadyRegisteredError(ApplicationError):
    """A User already exists for the Telegram account."""


class RequiredSystemRoleMissingError(ApplicationError):
    """A required system role is absent or incorrectly configured."""
