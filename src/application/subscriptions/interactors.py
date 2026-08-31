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
from application.subscriptions.commands import ActivateSubscriptionCommand
from application.subscriptions.dto import (
    ActivateSubscriptionResult,
    GetMySubscriptionResult,
    MySubscriptionDetails,
    SubscriptionPlanSummary,
)
from application.subscriptions.errors import (
    ActiveSubscriptionAlreadyExistsError,
    SubscriptionGroupForbiddenError,
    SubscriptionGroupRequiredError,
    SubscriptionPlanInactiveError,
    SubscriptionPlanNotApplicableToGroupError,
    SubscriptionPlanNotFoundError,
)
from application.subscriptions.lifecycle import (
    expire_if_elapsed,
    resolve_effective_active_subscription,
)
from application.subscriptions.ports import (
    MySubscriptionReader,
    SubscriptionPlanReader,
    SubscriptionPlanRepository,
    SubscriptionRepository,
)
from application.subscriptions.queries import (
    GetMySubscriptionQuery,
    ListActiveSubscriptionPlansQuery,
)
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)

SUBSCRIPTION_ACTIVATED_ACTION = "SUBSCRIPTION_ACTIVATED"
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
