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
    """The use case requires administrative access."""


class AthletePermissionRequiredError(ApplicationError):
    """The use case requires the ATHLETE system role."""


class TrainerPermissionRequiredError(ApplicationError):
    """The use case requires the TRAINER system role."""


class LastUserRoleRemovalForbiddenError(ApplicationError):
    """A User must retain at least one active system role."""


class AthleteNotFoundError(ApplicationError):
    """The requested Athlete does not exist."""


class AthleteProfileNotFoundError(ApplicationError):
    """The current User has no linked Athlete profile."""


class AthleteAlreadyLinkedError(ApplicationError):
    """The Athlete is already linked to a User."""


class OwnerRoleManagementForbiddenError(ApplicationError):
    """OWNER cannot be assigned or removed through Telegram role management."""


class OwnerAlreadyAssignedError(ApplicationError):
    """OWNER is already assigned to a different User."""
