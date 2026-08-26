from sqlalchemy.exc import IntegrityError

from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
)

ACTIVE_SUBSCRIPTION_CONSTRAINT = "uq_subscriptions_active_athlete_id"


def translate_integrity_error(error: IntegrityError) -> BaseException:
    if (
        getattr(error.orig, "sqlstate", None) == "23505"
        and _constraint_name(error) == ACTIVE_SUBSCRIPTION_CONSTRAINT
    ):
        return ActiveSubscriptionAlreadyExistsError()
    return error


def _constraint_name(error: IntegrityError) -> str | None:
    cause = getattr(error.orig, "__cause__", None)
    cause_constraint = getattr(cause, "constraint_name", None)
    if isinstance(cause_constraint, str):
        return cause_constraint

    direct_constraint = getattr(error.orig, "constraint_name", None)
    if isinstance(direct_constraint, str):
        return direct_constraint

    diagnostic = getattr(error.orig, "diag", None)
    diagnostic_constraint = getattr(diagnostic, "constraint_name", None)
    return (
        diagnostic_constraint
        if isinstance(diagnostic_constraint, str)
        else None
    )
