from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from application.common import UnitOfWork
from application.training_sessions.commands import (
    GenerateTrainingSessionsCommand,
)
from application.training_sessions.dto import (
    GenerateTrainingSessionsResult,
    NewTrainingSession,
    ScheduleRuleDescriptor,
    ScheduleRuleForGeneration,
    TrainingGroupWithoutTrainer,
)
from application.training_sessions.errors import (
    InvalidGenerationWindowError,
    MissingTrainingGroupTrainersError,
)
from application.training_sessions.ports import (
    ScheduleRuleRepository,
    TrainingSessionRepository,
)
from domain.club import TrainingSessionStatus

SUNDAY = 6


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
