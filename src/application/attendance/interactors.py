from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from application.attendance.commands import ConfirmAttendanceCommand
from application.attendance.dto import (
    AttendanceAthleteDetails,
    AttendanceSessionCandidate,
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
    ConfirmedAttendanceSession,
    SelectableAttendanceSession,
)
from application.attendance.errors import AttendanceAlreadyExistsError
from application.attendance.ports import (
    AttendanceRepository,
    AttendanceSessionRepository,
)
from application.common import Clock, UnitOfWork
from application.identity.authorization import require_administrative_actor
from application.identity.errors import AthleteNotFoundError
from application.identity.ports import (
    AthleteRepository,
    AuditLogRepository,
    RoleRepository,
    UserRepository,
)
from application.subscriptions import (
    SubscriptionPlanRepository,
    SubscriptionRepository,
    expire_if_elapsed,
    resolve_effective_active_subscription,
)
from domain.attendance import Attendance, AttendanceStatus
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.identity import Athlete
from domain.subscriptions import (
    Subscription,
    SubscriptionAccessScope,
    SubscriptionStatus,
)

ATTENDANCE_CREATED_ACTION = "ATTENDANCE_CREATED"
ATTENDANCE_ENTITY_TYPE = "ATTENDANCE"
SUBSCRIPTION_EXPIRED_ACTION = "SUBSCRIPTION_EXPIRED"
SUBSCRIPTION_ENTITY_TYPE = "SUBSCRIPTION"
TIME_ELAPSED_REASON = "TIME_ELAPSED"
VISITS_EXHAUSTED_REASON = "VISITS_EXHAUSTED"
CONFIRM_ATTENDANCE_AUDIT_SOURCE = "CONFIRM_ATTENDANCE"


class ConfirmAttendanceInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        subscription_repository: SubscriptionRepository,
        subscription_plan_repository: SubscriptionPlanRepository,
        training_session_repository: AttendanceSessionRepository,
        attendance_repository: AttendanceRepository,
        audit_log_repository: AuditLogRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._subscriptions = subscription_repository
        self._plans = subscription_plan_repository
        self._sessions = training_session_repository
        self._attendances = attendance_repository
        self._audit_log = audit_log_repository
        self._uow = unit_of_work
        self._clock = clock
        self._club_timezone = club_timezone

    async def __call__(
        self,
        command: ConfirmAttendanceCommand,
    ) -> ConfirmAttendanceResult:
        reference_now = self._clock.now()
        athlete_details: AttendanceAthleteDetails | None = None
        confirmed_session: ConfirmedAttendanceSession | None = None
        try:
            async with self._uow:
                actor = await require_administrative_actor(
                    telegram_id=command.actor_telegram_id,
                    users=self._users,
                    roles=self._roles,
                )
                if actor.id is None:
                    raise RuntimeError("A persisted User must have an id")

                athlete = await self._athletes.get_by_public_id_for_update(
                    command.athlete_public_id
                )
                if athlete is None or athlete.id is None:
                    raise AthleteNotFoundError
                athlete_details = _athlete_details(athlete)

                subscription = (
                    await self._subscriptions.get_active_by_athlete_for_update(
                        athlete.id
                    )
                )
                if subscription is None:
                    return _result(
                        ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION,
                        athlete_details,
                    )

                if await expire_if_elapsed(
                    subscription,
                    reference_now=reference_now,
                    repository=self._subscriptions,
                ):
                    await self._add_expiration_audit(
                        subscription=subscription,
                        athlete_id=athlete.id,
                        reference_now=reference_now,
                        reason=TIME_ELAPSED_REASON,
                    )
                    await self._uow.commit()
                    return _result(
                        ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED,
                        athlete_details,
                    )

                effective = resolve_effective_active_subscription(
                    subscription,
                    reference_now,
                )
                if effective is None:
                    return _result(
                        ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION,
                        athlete_details,
                    )

                if effective.remaining_visits == 0:
                    await self._expire_exhausted_subscription(
                        subscription=effective,
                        athlete_id=athlete.id,
                        reference_now=reference_now,
                    )
                    await self._uow.commit()
                    return _result(
                        ConfirmAttendanceOutcome.VISITS_EXHAUSTED,
                        athlete_details,
                    )

                plan = await self._plans.get_by_id(effective.plan_id)
                if plan is None:
                    raise RuntimeError(
                        "A persisted Subscription must reference a plan"
                    )

                day_start, day_end = _current_local_day_boundaries(
                    reference_now=reference_now,
                    club_timezone=self._club_timezone,
                )
                session_result = await self._resolve_session(
                    command=command,
                    subscription=effective,
                    access_scope=plan.access_scope,
                    day_start=day_start,
                    day_end=day_end,
                    athlete=athlete_details,
                )
                if isinstance(session_result, ConfirmAttendanceResult):
                    return session_result
                session = session_result
                confirmed_session = _confirmed_session(
                    session,
                    self._club_timezone,
                )

                if await self._attendances.exists(
                    training_session_id=session.id,
                    athlete_id=athlete.id,
                ):
                    return _result(
                        ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS,
                        athlete_details,
                        session=confirmed_session,
                        remaining_visits=effective.remaining_visits,
                    )

                attendance_id = await self._attendances.add(
                    Attendance(
                        id=None,
                        training_session_id=session.id,
                        athlete_id=athlete.id,
                        subscription_id=_persisted_id(effective),
                        confirmed_by_user_id=actor.id,
                        source=command.source,
                        status=AttendanceStatus.CONFIRMED,
                        confirmed_at=reference_now,
                    )
                )

                remaining_visits = effective.remaining_visits
                subscription_finished = False
                if remaining_visits is not None:
                    expected_remaining_visits = remaining_visits
                    remaining_visits -= 1
                    subscription_finished = remaining_visits == 0
                    updated = await self._subscriptions.update_attendance_state(
                        subscription_id=_persisted_id(effective),
                        expected_remaining_visits=expected_remaining_visits,
                        remaining_visits=remaining_visits,
                        status=(
                            SubscriptionStatus.EXPIRED
                            if subscription_finished
                            else SubscriptionStatus.ACTIVE
                        ),
                    )
                    if not updated:
                        raise RuntimeError(
                            "The locked Subscription attendance state changed"
                        )

                await self._audit_log.add(
                    actor_user_id=actor.id,
                    action=ATTENDANCE_CREATED_ACTION,
                    entity_type=ATTENDANCE_ENTITY_TYPE,
                    entity_id=attendance_id,
                    payload={
                        "athlete_id": athlete.id,
                        "training_session_id": session.id,
                        "subscription_id": _persisted_id(effective),
                        "source": command.source.value,
                        "confirmed_at": reference_now.isoformat(),
                    },
                )
                if subscription_finished:
                    await self._add_expiration_audit(
                        subscription=effective,
                        athlete_id=athlete.id,
                        reference_now=reference_now,
                        reason=VISITS_EXHAUSTED_REASON,
                    )

                await self._uow.commit()
                return _result(
                    ConfirmAttendanceOutcome.CONFIRMED,
                    athlete_details,
                    session=confirmed_session,
                    remaining_visits=remaining_visits,
                    subscription_finished=subscription_finished,
                )
        except AttendanceAlreadyExistsError:
            if athlete_details is None or confirmed_session is None:
                raise
            return _result(
                ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS,
                athlete_details,
                session=confirmed_session,
            )

    async def _resolve_session(
        self,
        *,
        command: ConfirmAttendanceCommand,
        subscription: Subscription,
        access_scope: SubscriptionAccessScope,
        day_start: datetime,
        day_end: datetime,
        athlete: AttendanceAthleteDetails,
    ) -> AttendanceSessionCandidate | ConfirmAttendanceResult:
        if access_scope is SubscriptionAccessScope.SPECIFIC_GROUP:
            if subscription.group_id is None:
                raise RuntimeError(
                    "SPECIFIC_GROUP Subscription must reference a group"
                )
            candidates = await self._sessions.list_by_group_for_update(
                training_group_id=subscription.group_id,
                starts_at_from=day_start,
                starts_at_to=day_end,
            )
            if not candidates:
                return _result(
                    ConfirmAttendanceOutcome.NO_TRAINING_SESSION,
                    athlete,
                )
            if len(candidates) > 1:
                return _result(
                    ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS,
                    athlete,
                )
            candidate = candidates[0]
        else:
            if command.training_session_id is None:
                candidates = await self._sessions.list_regular(
                    starts_at_from=day_start,
                    starts_at_to=day_end,
                )
                return ConfirmAttendanceResult(
                    outcome=(
                        ConfirmAttendanceOutcome.SESSION_SELECTION_REQUIRED
                    ),
                    athlete=athlete,
                    sessions=tuple(
                        _selectable_session(item, self._club_timezone)
                        for item in candidates
                    ),
                )
            selected_candidate = await self._sessions.get_by_id_for_update(
                command.training_session_id
            )
            if (
                selected_candidate is None
                or selected_candidate.group_type
                is not TrainingGroupType.REGULAR
                or not day_start <= selected_candidate.starts_at < day_end
            ):
                return _result(
                    ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED,
                    athlete,
                )
            candidate = selected_candidate

        session = _confirmed_session(candidate, self._club_timezone)
        if candidate.status is TrainingSessionStatus.CANCELLED:
            return _result(
                ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED,
                athlete,
                session=session,
                remaining_visits=subscription.remaining_visits,
            )
        return candidate

    async def _expire_exhausted_subscription(
        self,
        *,
        subscription: Subscription,
        athlete_id: int,
        reference_now: datetime,
    ) -> None:
        expired = await self._subscriptions.mark_expired(
            _persisted_id(subscription)
        )
        if not expired:
            raise RuntimeError("The locked ACTIVE Subscription was not expired")
        await self._add_expiration_audit(
            subscription=subscription,
            athlete_id=athlete_id,
            reference_now=reference_now,
            reason=VISITS_EXHAUSTED_REASON,
        )

    async def _add_expiration_audit(
        self,
        *,
        subscription: Subscription,
        athlete_id: int,
        reference_now: datetime,
        reason: str,
    ) -> None:
        await self._audit_log.add(
            actor_user_id=None,
            action=SUBSCRIPTION_EXPIRED_ACTION,
            entity_type=SUBSCRIPTION_ENTITY_TYPE,
            entity_id=_persisted_id(subscription),
            payload={
                "athlete_id": athlete_id,
                "reason": reason,
                "source": CONFIRM_ATTENDANCE_AUDIT_SOURCE,
                "expired_at": reference_now.isoformat(),
            },
        )


def _current_local_day_boundaries(
    *,
    reference_now: datetime,
    club_timezone: ZoneInfo,
) -> tuple[datetime, datetime]:
    local_date = reference_now.astimezone(club_timezone).date()
    local_start = datetime.combine(local_date, time.min, tzinfo=club_timezone)
    local_end = datetime.combine(
        local_date + timedelta(days=1),
        time.min,
        tzinfo=club_timezone,
    )
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _athlete_details(athlete: Athlete) -> AttendanceAthleteDetails:
    return AttendanceAthleteDetails(
        full_name=" ".join(
            part for part in (athlete.first_name, athlete.last_name) if part
        ),
        birth_date=athlete.birth_date,
    )


def _confirmed_session(
    session: AttendanceSessionCandidate,
    club_timezone: ZoneInfo,
) -> ConfirmedAttendanceSession:
    return ConfirmedAttendanceSession(
        starts_at=session.starts_at.astimezone(club_timezone),
        sport_direction_name=session.sport_direction_name,
        group_name=session.group_name,
    )


def _selectable_session(
    session: AttendanceSessionCandidate,
    club_timezone: ZoneInfo,
) -> SelectableAttendanceSession:
    return SelectableAttendanceSession(
        training_session_id=session.id,
        starts_at=session.starts_at.astimezone(club_timezone),
        status=session.status,
        sport_direction_name=session.sport_direction_name,
        group_name=session.group_name,
        selectable=session.status is not TrainingSessionStatus.CANCELLED,
    )


def _result(
    outcome: ConfirmAttendanceOutcome,
    athlete: AttendanceAthleteDetails,
    *,
    session: ConfirmedAttendanceSession | None = None,
    remaining_visits: int | None = None,
    subscription_finished: bool = False,
) -> ConfirmAttendanceResult:
    return ConfirmAttendanceResult(
        outcome=outcome,
        athlete=athlete,
        session=session,
        remaining_visits=remaining_visits,
        subscription_finished=subscription_finished,
    )


def _persisted_id(subscription: Subscription) -> int:
    if subscription.id is None:
        raise RuntimeError("A persisted Subscription must have an id")
    return subscription.id
