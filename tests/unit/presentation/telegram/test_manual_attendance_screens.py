from datetime import UTC, datetime
from uuid import UUID

from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message

from application.athletes import AthleteSelectionItem
from application.attendance import (
    AttendanceAthleteDetails,
    ConfirmAttendanceOutcome,
    ConfirmAttendanceResult,
    ConfirmedAttendanceSession,
    SelectableAttendanceSession,
)
from domain.club import TrainingSessionStatus
from presentation.telegram.handlers.manual_attendance import (
    ManualAttendanceAction,
    ManualAttendanceCallback,
    _confirm,
    _terminal_text,
    build_session_selection_keyboard,
)

NOW = datetime(2026, 9, 1, 19, tzinfo=UTC)


def _session(*, selectable: bool) -> SelectableAttendanceSession:
    return SelectableAttendanceSession(
        training_session_id=10,
        starts_at=NOW,
        status=(
            TrainingSessionStatus.SCHEDULED
            if selectable
            else TrainingSessionStatus.CANCELLED
        ),
        sport_direction_name="Кикбоксинг",
        group_name="Взрослые",
        selectable=selectable,
    )


def _result(
    outcome: ConfirmAttendanceOutcome,
    *,
    remaining: int | None = None,
    finished: bool = False,
) -> ConfirmAttendanceResult:
    return ConfirmAttendanceResult(
        outcome=outcome,
        athlete=AttendanceAthleteDetails("Иван Иванов", None),
        session=ConfirmedAttendanceSession(
            starts_at=NOW,
            sport_direction_name="Кикбоксинг",
            group_name="Взрослые",
        ),
        remaining_visits=remaining,
        subscription_finished=finished,
    )


def test_cancelled_session_is_visible_but_uses_non_confirming_callback() -> None:
    keyboard = build_session_selection_keyboard(
        (_session(selectable=True), _session(selectable=False))
    )
    callbacks = {
        button.callback_data: button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    assert callbacks[
        ManualAttendanceCallback(
            action=ManualAttendanceAction.CANCELLED,
            value=10,
        ).pack()
    ].endswith("— Отменена")


def test_success_and_last_visit_are_distinct_success_states() -> None:
    regular = _terminal_text(
        _result(ConfirmAttendanceOutcome.CONFIRMED, remaining=7)
    )
    last = _terminal_text(
        _result(
            ConfirmAttendanceOutcome.CONFIRMED,
            remaining=0,
            finished=True,
        )
    )

    assert regular.startswith("Посещение отмечено")
    assert "Осталось посещений: 7" in regular
    assert last.startswith("Посещение отмечено")
    assert "последнее посещение" in last


def test_controlled_terminal_outcomes_have_expected_messages() -> None:
    expected = {
        ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION: "Нет активного",
        ConfirmAttendanceOutcome.SUBSCRIPTION_EXPIRED: "Абонемент истёк",
        ConfirmAttendanceOutcome.VISITS_EXHAUSTED: "Посещения закончились",
        ConfirmAttendanceOutcome.NO_TRAINING_SESSION: "нет тренировки",
        ConfirmAttendanceOutcome.TRAINING_SESSION_CANCELLED: "отменена",
        ConfirmAttendanceOutcome.ATTENDANCE_ALREADY_EXISTS: "уже отмечено",
        ConfirmAttendanceOutcome.TRAINING_SESSION_NOT_ALLOWED: "недоступна",
        ConfirmAttendanceOutcome.TRAINING_SESSION_AMBIGUOUS: "несколько",
    }

    for outcome, fragment in expected.items():
        assert fragment in _terminal_text(_result(outcome))


async def test_manual_source_and_actor_are_set_server_side() -> None:
    calls = []

    async def interactor(command):  # type: ignore[no-untyped-def]
        calls.append(command)
        return _result(ConfirmAttendanceOutcome.NO_ACTIVE_SUBSCRIPTION)

    message = Message(
        message_id=1,
        date=NOW,
        chat=Chat(id=55, type=ChatType.PRIVATE),
    )
    athlete = AthleteSelectionItem(
        athlete_id=3,
        athlete_public_id=UUID(int=3),
        first_name="Иван",
        last_name="Иванов",
        birth_date=None,
    )
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=55, user_id=55),
    )

    result = await _confirm(
        actor_telegram_id=55,
        athlete_public_id=athlete.athlete_public_id,
        attendance_interactor=interactor,  # type: ignore[arg-type]
        message=message,
        state=state,
        renderer=object(),  # type: ignore[arg-type]
    )

    assert result is not None
    assert calls[0].actor_telegram_id == 55
    assert calls[0].athlete_public_id == athlete.athlete_public_id
    assert calls[0].source.value == "MANUAL"
    assert calls[0].training_session_id is None
