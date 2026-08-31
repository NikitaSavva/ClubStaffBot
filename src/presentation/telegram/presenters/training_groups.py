from collections import defaultdict

from application.club import ScheduleRuleSummary, TrainingGroupSummary

_WEEKDAY_LABELS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")


def format_training_group_label(group: TrainingGroupSummary) -> str:
    direction_name = group.direction_short_name or group.direction_name
    schedule = format_schedule_summary(
        group.schedule_rules,
        include_end_time=False,
    )
    return f"{direction_name} · {group.group_name} — {schedule}"


def format_training_group_button_label(group: TrainingGroupSummary) -> str:
    direction_name = group.direction_short_name or group.direction_name
    start_time = min(
        (rule.start_time for rule in group.schedule_rules),
        default=None,
    )
    start_time_label = (
        start_time.strftime("%H:%M")
        if start_time is not None
        else "время не задано"
    )
    return f"{direction_name} · {group.group_name} · {start_time_label}"


def format_training_group_details(group: TrainingGroupSummary) -> str:
    schedule = format_schedule_summary(
        group.schedule_rules,
        include_end_time=True,
    )
    return f"{group.direction_name} · {group.group_name}\n{schedule}"


def format_schedule_summary(
    rules: tuple[ScheduleRuleSummary, ...],
    *,
    include_end_time: bool,
) -> str:
    if not rules:
        return "расписание не задано"

    weekdays_by_time: dict[tuple[str, str], list[int]] = defaultdict(list)
    for rule in sorted(
        rules,
        key=lambda item: (item.start_time, item.end_time, item.weekday),
    ):
        weekdays_by_time[
            (
                rule.start_time.strftime("%H:%M"),
                rule.end_time.strftime("%H:%M"),
            )
        ].append(rule.weekday)

    parts = []
    for (start_time, end_time), weekdays in weekdays_by_time.items():
        time_label = (
            f"{start_time}–{end_time}" if include_end_time else start_time
        )
        parts.append(f"{_format_weekdays(weekdays)} {time_label}")
    return "; ".join(parts)


def _format_weekdays(weekdays: list[int]) -> str:
    ordered = sorted(set(weekdays))
    if not ordered or any(day < 0 or day >= len(_WEEKDAY_LABELS) for day in ordered):
        return "дни не указаны"
    if len(ordered) >= 4 and ordered == list(
        range(ordered[0], ordered[-1] + 1)
    ):
        return f"{_WEEKDAY_LABELS[ordered[0]]}–{_WEEKDAY_LABELS[ordered[-1]]}"
    return "/".join(_WEEKDAY_LABELS[day] for day in ordered)
