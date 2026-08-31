from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from application.common import Clock, UnitOfWork
from application.identity.authorization import (
    require_administrative_actor,
    require_athlete_actor,
    require_trainer_actor,
)
from application.identity.errors import AthleteProfileNotFoundError
from application.identity.ports import RoleRepository, UserRepository
from application.subscriptions import (
    MySubscriptionReader,
    resolve_effective_active_subscription,
)
from application.training_sessions.commands import (
    GenerateTrainingSessionsCommand,
)
from application.training_sessions.dto import (
    CurrentWeekScheduleFilters,
    GenerateTrainingSessionsResult,
    GetCurrentWeekScheduleResult,
    NewTrainingSession,
    ScheduleRuleDescriptor,
    ScheduleRuleForGeneration,
    ScheduleSessionItem,
    ScheduleWeek,
    TrainingGroupWithoutTrainer,
)
from application.training_sessions.errors import (
    InvalidGenerationWindowError,
    MissingTrainingGroupTrainersError,
)
from application.training_sessions.ports import (
    CurrentWeekScheduleReader,
    ScheduleRuleRepository,
    TrainingSessionRepository,
)
from application.training_sessions.queries import GetCurrentWeekScheduleQuery
from domain.club import TrainingGroupType, TrainingSessionStatus
from domain.identity import SystemRoleCode, User
from domain.subscriptions import SubscriptionAccessScope

SUNDAY = 6


class GetCurrentWeekScheduleInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        subscription_reader: MySubscriptionReader,
        schedule_reader: CurrentWeekScheduleReader,
        clock: Clock,
        club_timezone: ZoneInfo,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._subscriptions = subscription_reader
        self._schedule = schedule_reader
        self._clock = clock
        self._club_timezone = club_timezone

    async def __call__(
        self,
        query: GetCurrentWeekScheduleQuery,
    ) -> GetCurrentWeekScheduleResult:
        actor = await self._authorize(query)
        if actor.id is None:
            raise RuntimeError("A persisted User must have an id")

        reference_now = self._clock.now()
        filters = _current_week_filters(
            reference_now=reference_now,
            club_timezone=self._club_timezone,
        )
        if query.selected_role is SystemRoleCode.ATHLETE:
            read_model = await self._subscriptions.get_by_user_id(actor.id)
            if read_model is None:
                raise AthleteProfileNotFoundError
            persisted = read_model.persisted_active
            effective = resolve_effective_active_subscription(
                persisted.subscription if persisted is not None else None,
                reference_now,
            )
            if effective is None or persisted is None:
                return GetCurrentWeekScheduleResult(schedule=None)
            if persisted.access_scope is SubscriptionAccessScope.SPECIFIC_GROUP:
                if effective.group_id is None:
                    raise RuntimeError(
                        "SPECIFIC_GROUP Subscription must have a group"
                    )
                filters = CurrentWeekScheduleFilters(
                    week_start=filters.week_start,
                    week_end=filters.week_end,
                    training_group_id=effective.group_id,
                )
            else:
                filters = CurrentWeekScheduleFilters(
                    week_start=filters.week_start,
                    week_end=filters.week_end,
                    group_type=TrainingGroupType.REGULAR,
                )
        elif query.selected_role is SystemRoleCode.TRAINER:
            filters = CurrentWeekScheduleFilters(
                week_start=filters.week_start,
                week_end=filters.week_end,
                trainer_id=actor.id,
            )

        sessions = await self._schedule.list(filters)
        local_week_start = filters.week_start.astimezone(self._club_timezone)
        local_week_end = filters.week_end.astimezone(self._club_timezone)
        return GetCurrentWeekScheduleResult(
            schedule=ScheduleWeek(
                week_start=local_week_start,
                week_end=local_week_end,
                sessions=tuple(
                    ScheduleSessionItem(
                        id=item.id,
                        training_group_id=item.training_group_id,
                        starts_at=item.starts_at.astimezone(
                            self._club_timezone
                        ),
                        ends_at=item.ends_at.astimezone(self._club_timezone),
                        status=item.status,
                        sport_direction_name=item.sport_direction_name,
                        group_name=item.group_name,
                    )
                    for item in sessions
                ),
            )
        )

    async def _authorize(self, query: GetCurrentWeekScheduleQuery) -> User:
        if query.selected_role is SystemRoleCode.ATHLETE:
            return await require_athlete_actor(
                telegram_id=query.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
        if query.selected_role is SystemRoleCode.TRAINER:
            return await require_trainer_actor(
                telegram_id=query.actor_telegram_id,
                users=self._users,
                roles=self._roles,
            )
        return await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
            required_role=query.selected_role,
        )


def _current_week_filters(
    *,
    reference_now: datetime,
    club_timezone: ZoneInfo,
) -> CurrentWeekScheduleFilters:
    local_date = reference_now.astimezone(club_timezone).date()
    monday = local_date - timedelta(days=local_date.weekday())
    sunday = monday + timedelta(days=6)
    local_start = datetime.combine(monday, time.min, tzinfo=club_timezone)
    local_end = datetime.combine(sunday, time.min, tzinfo=club_timezone)
    return CurrentWeekScheduleFilters(
        week_start=local_start.astimezone(UTC),
        week_end=local_end.astimezone(UTC),
    )


class GenerateTrainingSessionsInteractor:
    def __init__(
        self,
        schedule_rule_repository: ScheduleRuleRepository,
        training_session_repository: TrainingSessionRepository,
        unit_of_work: UnitOfWork,
        club_timezone: ZoneInfo,
    ) -> None:
        self._schedule_rules = schedule_rule_repository
        self._training_sessions = training_session_repository
        self._uow = unit_of_work
        self._club_timezone = club_timezone

    async def __call__(
        self,
        command: GenerateTrainingSessionsCommand,
    ) -> GenerateTrainingSessionsResult:
        if command.date_from > command.date_to:
            raise InvalidGenerationWindowError

        async with self._uow:
            rules = await self._schedule_rules.list_for_generation(
                date_from=command.date_from,
                date_to=command.date_to,
            )
            sessions, missing_trainers = self._prepare_sessions(
                rules=rules,
                date_from=command.date_from,
                date_to=command.date_to,
            )
            if missing_trainers:
                raise MissingTrainingGroupTrainersError(missing_trainers)

            created_count = await self._training_sessions.add_missing(sessions)
            await self._uow.commit()

        return GenerateTrainingSessionsResult(
            date_from=command.date_from,
            date_to=command.date_to,
            created_count=created_count,
            skipped_count=len(sessions) - created_count,
        )

    def _prepare_sessions(
        self,
        *,
        rules: tuple[ScheduleRuleForGeneration, ...],
        date_from: date,
        date_to: date,
    ) -> tuple[
        tuple[NewTrainingSession, ...],
        tuple[TrainingGroupWithoutTrainer, ...],
    ]:
        sessions: list[NewTrainingSession] = []
        missing_rules: dict[
            tuple[int, str, str],
            set[ScheduleRuleDescriptor],
        ] = defaultdict(set)

        for rule in rules:
            occurrence_dates = _occurrence_dates(rule, date_from, date_to)
            if not occurrence_dates:
                continue
            if rule.trainer_id is None:
                missing_rules[
                    (
                        rule.training_group_id,
                        rule.direction_name,
                        rule.group_name,
                    )
                ].add(
                    ScheduleRuleDescriptor(
                        weekday=rule.weekday,
                        start_time=rule.start_time,
                        end_time=rule.end_time,
                    )
                )
                continue

            for occurrence_date in occurrence_dates:
                sessions.append(
                    NewTrainingSession(
                        schedule_rule_id=rule.schedule_rule_id,
                        training_group_id=rule.training_group_id,
                        trainer_id=rule.trainer_id,
                        starts_at=datetime.combine(
                            occurrence_date,
                            rule.start_time,
                            tzinfo=self._club_timezone,
                        ),
                        ends_at=datetime.combine(
                            occurrence_date,
                            rule.end_time,
                            tzinfo=self._club_timezone,
                        ),
                        status=TrainingSessionStatus.SCHEDULED,
                        is_overridden=False,
                    )
                )

        missing_trainers = tuple(
            TrainingGroupWithoutTrainer(
                training_group_id=group_id,
                direction_name=direction_name,
                group_name=group_name,
                schedule=tuple(sorted(schedule)),
            )
            for (group_id, direction_name, group_name), schedule in sorted(
                missing_rules.items(),
                key=lambda item: (
                    item[0][1],
                    item[0][2],
                    item[0][0],
                ),
            )
        )
        sessions.sort(key=lambda item: (item.starts_at, item.schedule_rule_id))
        return tuple(sessions), missing_trainers


def _occurrence_dates(
    rule: ScheduleRuleForGeneration,
    date_from: date,
    date_to: date,
) -> tuple[date, ...]:
    if not rule.is_active or rule.weekday == SUNDAY:
        return ()

    first_date = date_from + timedelta(
        days=(rule.weekday - date_from.weekday()) % 7
    )
    occurrence_dates: list[date] = []
    occurrence_date = first_date
    while occurrence_date <= date_to:
        if (
            (rule.valid_from is None or occurrence_date >= rule.valid_from)
            and (
                rule.valid_until is None
                or occurrence_date <= rule.valid_until
            )
        ):
            occurrence_dates.append(occurrence_date)
        occurrence_date += timedelta(days=7)
    return tuple(occurrence_dates)
