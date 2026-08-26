from application.errors import ApplicationError


class SubscriptionPlanNotFoundError(ApplicationError):
    """The selected SubscriptionPlan does not exist."""


class SubscriptionPlanInactiveError(ApplicationError):
    """The selected SubscriptionPlan is not active."""


class SubscriptionGroupRequiredError(ApplicationError):
    """The selected plan requires one TrainingGroup."""


class SubscriptionGroupForbiddenError(ApplicationError):
    """The selected plan must not be tied to one TrainingGroup."""


class SubscriptionPlanNotApplicableToGroupError(ApplicationError):
    """The selected plan does not apply to the TrainingGroup type."""


class ActiveSubscriptionAlreadyExistsError(ApplicationError):
    """The Athlete already has a persisted non-elapsed ACTIVE Subscription."""
