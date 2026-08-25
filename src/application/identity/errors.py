from application.errors import ApplicationError


class InvalidBotInviteError(ApplicationError):
    """The supplied reception invite cannot authorize registration."""


class UserAlreadyRegisteredError(ApplicationError):
    """A User already exists for the Telegram account."""


class RequiredSystemRoleMissingError(ApplicationError):
    """A required system role is absent or incorrectly configured."""


class UserNotFoundError(ApplicationError):
    """No registered User exists for the supplied identity."""


class UserHasNoRolesError(ApplicationError):
    """The User has no active system roles that can provide a menu."""


class AdministratorPermissionRequiredError(ApplicationError):
    """The use case requires an active ADMINISTRATOR role."""


class LastUserRoleRemovalForbiddenError(ApplicationError):
    """A User must retain at least one active system role."""


class AthleteNotFoundError(ApplicationError):
    """The requested Athlete does not exist."""


class AthleteAlreadyLinkedError(ApplicationError):
    """The Athlete is already linked to a User."""
