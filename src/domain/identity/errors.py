from domain.errors import DomainError


class AthleteFirstNameRequiredError(DomainError):
    """An Athlete cannot be created without a non-blank first name."""


class AthleteLastNameRequiredError(DomainError):
    """A manually created Athlete requires a non-blank last name."""


class AthleteBirthDateRequiredError(DomainError):
    """A manually created Athlete requires a birth date."""
