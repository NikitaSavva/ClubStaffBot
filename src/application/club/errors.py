from application.errors import ApplicationError


class TrainingGroupNotFoundError(ApplicationError):
    """The selected TrainingGroup does not exist."""


class TargetUserIsNotTrainerError(ApplicationError):
    """The target User does not have the active system TRAINER role."""


class TrainingGroupTrainerAlreadyAssignedError(ApplicationError):
    """A TrainingGroup default Trainer cannot be replaced by this use case."""
