from domain.errors import DomainError


class AthleteFirstNameRequiredError(DomainError):
    """An Athlete cannot be created without a non-blank first name."""
