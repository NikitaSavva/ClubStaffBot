from datetime import datetime

from dateutil.relativedelta import relativedelta  # type: ignore[import-untyped]

from application.club.errors import TrainingGroupNotFoundError
from application.club.ports import TrainingGroupRepository
from application.common import Clock, UnitOfWork
from application.identity.authorization import (
    require_administrative_actor,
    require_athlete_actor,
)
from application.identity.errors import (
    AthleteNotFoundError,
    AthleteProfileNotFoundError,
)
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    RoleRepository,
    UserRepository,
)
from application.subscriptions.commands import (
    ActivateSubscriptionCommand,
    CorrectSubscriptionCommand,
)
from application.subscriptions.dto import (
    ActivateSubscriptionResult,
    CorrectSubscriptionOutcome,
    CorrectSubscriptionResult,
    GetLatestAthleteSubscriptionResult,
    GetMySubscriptionResult,
    MySubscriptionDetails,
    SubscriptionPlanSummary,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    InvalidRemainingVisitsError,
    InvalidSubscriptionExpirationError,
    LatestSubscriptionChangedError,
    LimitedSubscriptionRemainingVisitsRequiredError,
    SubscriptionGroupForbiddenError,
    SubscriptionGroupRequiredError,
    SubscriptionNotFoundError,
    SubscriptionPlanInactiveError,
    SubscriptionPlanNotApplicableToGroupError,
    SubscriptionPlanNotFoundError,
    UnlimitedSubscriptionRemainingVisitsForbiddenError,
)
from application.subscriptions.lifecycle import (
    expire_if_elapsed,
    resolve_effective_active_subscription,
)
from application.subscriptions.ports import (
    LatestAthleteSubscriptionReader,
    MySubscriptionReader,
    SubscriptionPlanReader,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from application.subscriptions.queries import (
    GetLatestAthleteSubscriptionQuery,
    GetMySubscriptionQuery,
    ListActiveSubscriptionPlansQuery,
)
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)

SUBSCRIPTION_ACTIVATED_ACTION = "SUBSCRIPTION_ACTIVATED"
SUBSCRIPTION_CORRECTED_ACTION = "SUBSCRIPTION_CORRECTED"
SUBSCRIPTION_ENTITY_TYPE = "SUBSCRIPTION"


class ListActiveSubscriptionPlansInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        subscription_plan_reader: SubscriptionPlanReader,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = subscription_plan_reader

    async def __call__(
        self,
        query: ListActiveSubscriptionPlansQuery,
    ) -> tuple[SubscriptionPlanSummary, ...]:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        return await self._reader.list_active()


class GetMySubscriptionInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reader: MySubscriptionReader,
        clock: Clock,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = reader
        self._clock = clock

    async def __call__(
        self,
        query: GetMySubscriptionQuery,
    ) -> GetMySubscriptionResult:
        actor = await require_athlete_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        if actor.id is None:
            raise RuntimeError("A persisted User must have an id")

        read_model = await self._reader.get_by_user_id(actor.id)
        if read_model is None:
            raise AthleteProfileNotFoundError

        reference_now = self._clock.now()
        persisted = read_model.persisted_active
        effective = resolve_effective_active_subscription(
            persisted.subscription if persisted is not None else None,
            reference_now,
        )
        if effective is None or persisted is None:
            return GetMySubscriptionResult(current=None)

        return GetMySubscriptionResult(
            current=MySubscriptionDetails(
                plan_name=persisted.plan_name,
                is_unlimited=persisted.is_unlimited,
                access_scope=persisted.access_scope,
                group=persisted.group,
                starts_at=effective.starts_at,
                expires_at=effective.expires_at,
                remaining_visits=effective.remaining_visits,
            )
        )


class GetLatestAthleteSubscriptionInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reader: LatestAthleteSubscriptionReader,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._reader = reader

    async def __call__(
        self,
        query: GetLatestAthleteSubscriptionQuery,
    ) -> GetLatestAthleteSubscriptionResult:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        read_model = await self._reader.get_by_athlete_id(query.athlete_id)
        if read_model is None:
            raise AthleteNotFoundError
        return GetLatestAthleteSubscriptionResult(
            athlete_id=read_model.athlete_id,
            athlete_full_name=read_model.athlete_full_name,
            latest=read_model.latest,
        )


class ActivateSubscriptionInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        training_group_repository: TrainingGroupRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        subscription_repository: SubscriptionRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._training_groups = training_group_repository
        self._plans = subscription_plan_repository
        self._subscriptions = subscription_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work
        self._clock = clock

    async def __call__(
        self,
        command: ActivateSubscriptionCommand,
    ) -> ActivateSubscriptionResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            if actor.id is None:
                raise RuntimeError("A persisted User must have an id")

            athlete = await self._athletes.get_by_id_for_update(
                command.athlete_id
            )
            if athlete is None or athlete.id is None:
                raise AthleteNotFoundError

            reference_now = self._clock.now()
            current = await self._subscriptions.get_active_by_athlete(
                athlete.id
            )
            if current is not None:
                expired = await expire_if_elapsed(
                    current,
                    reference_now=reference_now,
                    repository=self._subscriptions,
                )
                if not expired:
                    raise ActiveSubscriptionAlreadyExistsError
                # Materialize ACTIVE -> EXPIRED before a new ACTIVE INSERT.
                await self._uow.flush()

            plan = await self._plans.get_by_id(command.subscription_plan_id)
            if plan is None:
                raise SubscriptionPlanNotFoundError
            if not plan.is_active:
                raise SubscriptionPlanInactiveError

            group_id = command.training_group_id
            if plan.access_scope is SubscriptionAccessScope.SPECIFIC_GROUP:
                if group_id is None:
                    raise SubscriptionGroupRequiredError
                group = await self._training_groups.get_by_id(group_id)
                if group is None:
                    raise TrainingGroupNotFoundError
                if (
                    plan.required_group_type is not None
                    and group.group_type is not plan.required_group_type
                ):
                    raise SubscriptionPlanNotApplicableToGroupError
            elif group_id is not None:
                raise SubscriptionGroupForbiddenError

            expires_at = reference_now + relativedelta(
                months=plan.duration_months
            )
            subscription = Subscription(
                id=None,
                athlete_id=athlete.id,
                group_id=group_id,
                plan_id=plan.id,
                activated_by_user_id=actor.id,
                activated_at=reference_now,
                starts_at=reference_now,
                expires_at=expires_at,
                activation_price=plan.price,
                remaining_visits=plan.visit_limit,
                status=SubscriptionStatus.ACTIVE,
            )
            subscription_id = await self._subscriptions.add(subscription)
            await self._audit_log.add(
                actor_user_id=actor.id,
                action=SUBSCRIPTION_ACTIVATED_ACTION,
                entity_type=SUBSCRIPTION_ENTITY_TYPE,
                entity_id=subscription_id,
                payload={
                    "athlete_id": athlete.id,
                    "subscription_plan_id": plan.id,
                    "training_group_id": group_id,
                    "starts_at": reference_now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "initial_remaining_visits": plan.visit_limit,
                    "activation_price": str(plan.price),
                },
            )
            await self._uow.commit()

        athlete_full_name = " ".join(
            part for part in (athlete.first_name, athlete.last_name) if part
        )
        return ActivateSubscriptionResult(
            subscription_id=subscription_id,
            athlete_id=athlete.id,
            athlete_full_name=athlete_full_name,
            subscription_plan_id=plan.id,
            plan_name=plan.name,
            training_group_id=group_id,
            starts_at=reference_now,
            expires_at=expires_at,
            remaining_visits=plan.visit_limit,
        )


class CorrectSubscriptionInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        subscription_repository: SubscriptionRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._plans = subscription_plan_repository
        self._subscriptions = subscription_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work

    async def __call__(
        self,
        command: CorrectSubscriptionCommand,
    ) -> CorrectSubscriptionResult:
        async with self._uow:
            actor = await require_administrative_actor(
                telegram_id=command.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
            if actor.id is None:
                raise RuntimeError("A persisted User must have an id")

            athlete = await self._athletes.get_by_id_for_update(
                command.athlete_id
            )
            if athlete is None or athlete.id is None:
                raise AthleteNotFoundError

            subscription = await self._subscriptions.get_by_id_for_update(
                command.subscription_id
            )
            if (
                subscription is None
                or subscription.id is None
                or subscription.athlete_id != athlete.id
            ):
                raise SubscriptionNotFoundError

            latest_id = await self._subscriptions.get_latest_id_by_athlete(
                athlete.id
            )
            if latest_id != subscription.id:
                raise LatestSubscriptionChangedError

            plan = await self._plans.get_by_id(subscription.plan_id)
            if plan is None:
                raise SubscriptionPlanNotFoundError
            if plan.is_unlimited != (plan.visit_limit is None):
                raise RuntimeError("SubscriptionPlan unlimited metadata is invalid")

            remaining_visits = subscription.remaining_visits
            if command.remaining_visits_is_set:
                remaining_visits = command.remaining_visits
            _validate_remaining_visits(
                is_unlimited=plan.is_unlimited,
                remaining_visits=remaining_visits,
            )

            expires_at = command.expires_at or subscription.expires_at
            if expires_at.utcoffset() is None:
                raise InvalidSubscriptionExpirationError
            status = command.status or subscription.status

            changes = _correction_changes(
                subscription=subscription,
                remaining_visits=remaining_visits,
                expires_at=expires_at,
                status=status,
            )
            if not changes:
                return CorrectSubscriptionResult(
                    outcome=CorrectSubscriptionOutcome.NO_CHANGES,
                    athlete_id=athlete.id,
                    subscription_id=subscription.id,
                )

            if status is SubscriptionStatus.ACTIVE:
                other_active = (
                    await self._subscriptions.get_other_active_by_athlete(
                        athlete_id=athlete.id,
                        excluded_subscription_id=subscription.id,
                    )
                )
                if other_active is not None:
                    raise ActiveSubscriptionAlreadyExistsError

            updated = await self._subscriptions.update_correction(
                subscription_id=subscription.id,
                remaining_visits=remaining_visits,
                expires_at=expires_at,
                status=status,
            )
            if not updated:
                raise SubscriptionNotFoundError

            await self._audit_log.add(
                actor_user_id=actor.id,
                action=SUBSCRIPTION_CORRECTED_ACTION,
                entity_type=SUBSCRIPTION_ENTITY_TYPE,
                entity_id=subscription.id,
                payload={
                    "subscription_id": subscription.id,
                    "athlete_id": athlete.id,
                    "source": "ADMIN_CORRECTION",
                    "changes": changes,
                },
            )
            await self._uow.commit()

        return CorrectSubscriptionResult(
            outcome=CorrectSubscriptionOutcome.CORRECTED,
            athlete_id=athlete.id,
            subscription_id=subscription.id,
        )


def _validate_remaining_visits(
    *,
    is_unlimited: bool,
    remaining_visits: int | None,
) -> None:
    if is_unlimited:
        if remaining_visits is not None:
            raise UnlimitedSubscriptionRemainingVisitsForbiddenError
        return
    if remaining_visits is None:
        raise LimitedSubscriptionRemainingVisitsRequiredError
    if (
        isinstance(remaining_visits, bool)
        or not isinstance(remaining_visits, int)
        or remaining_visits < 0
    ):
        raise InvalidRemainingVisitsError


def _correction_changes(
    *,
    subscription: Subscription,
    remaining_visits: int | None,
    expires_at: datetime,
    status: SubscriptionStatus,
) -> dict[str, object]:
    changes: dict[str, object] = {}
    if remaining_visits != subscription.remaining_visits:
        changes["remaining_visits"] = {
            "before": subscription.remaining_visits,
            "after": remaining_visits,
        }
    if expires_at != subscription.expires_at:
        changes["expires_at"] = {
            "before": subscription.expires_at.isoformat(),
            "after": expires_at.isoformat(),
        }
    if status is not subscription.status:
        changes["status"] = {
            "before": subscription.status.value,
            "after": status.value,
        }
    return changes
