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
    """The Athlete has a conflicting persisted ACTIVE Subscription."""


class SubscriptionNotFoundError(ApplicationError):
    """The selected Subscription does not exist or belongs to another Athlete."""


class LatestSubscriptionChangedError(ApplicationError):
    """A newer Subscription was created after the correction flow started."""


class InvalidRemainingVisitsError(ApplicationError):
    """The corrected remaining visits value is invalid."""


class LimitedSubscriptionRemainingVisitsRequiredError(ApplicationError):
    """A limited Subscription must have a non-negative remaining visit count."""


class UnlimitedSubscriptionRemainingVisitsForbiddenError(ApplicationError):
    """An unlimited Subscription cannot have a remaining visit count."""


class InvalidSubscriptionExpirationError(ApplicationError):
    """The corrected expiration datetime must be timezone-aware."""
