from datetime import date
from uuid import UUID

import pytest

from application.athletes import (
    AthleteSearch,
    AthleteSearchKind,
    AthleteSelectionItem,
    AthleteSelectionPage,
)
from presentation.telegram.handlers.athlete_selector import (
    AthleteSelectionPurpose,
    AthleteSelectorAction,
    AthleteSelectorCallback,
    build_athlete_selector_keyboard,
    parse_athlete_search_input,
)


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_search_is_invalid(value: str) -> None:
    assert parse_athlete_search_input(value) is None


@pytest.mark.parametrize("value", ["@", "@@user", "@some user"])
def test_invalid_username_search(value: str) -> None:
    assert parse_athlete_search_input(value) is None


def test_search_kind_is_selected_only_by_at_prefix() -> None:
    assert parse_athlete_search_input(" Иванов ") == AthleteSearch(
        AthleteSearchKind.SURNAME,
        "Иванов",
    )
    assert parse_athlete_search_input(" @SomeUser ") == AthleteSearch(
        AthleteSearchKind.TELEGRAM_USERNAME,
        "SomeUser",
    )
    assert parse_athlete_search_input("SomeUser") == AthleteSearch(
        AthleteSearchKind.SURNAME,
        "SomeUser",
    )


def test_keyboard_keeps_purpose_and_page_without_search_value() -> None:
    item = AthleteSelectionItem(
        athlete_id=12,
        athlete_public_id=UUID(int=12),
        first_name="Иван",
        last_name="Иванов",
        birth_date=date(1991, 12, 27),
    )
    result = AthleteSelectionPage(
        items=(item,),
        page=1,
        has_previous=True,
        has_next=True,
    )
    search = AthleteSearch(AthleteSearchKind.SURNAME, "Иванов")

    keyboard = build_athlete_selector_keyboard(
        purpose=AthleteSelectionPurpose.ATTENDANCE,
        result=result,
        search=search,
    )
    callbacks = {
        button.callback_data: button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    }

    attendance_callback = AthleteSelectorCallback(
        purpose=AthleteSelectionPurpose.ATTENDANCE,
        action=AthleteSelectorAction.SELECT,
        value=str(item.athlete_public_id),
    ).pack()
    assert callbacks[attendance_callback] == "Иван Иванов (27.12.1991)"
    assert len(attendance_callback.encode()) <= 64
    assert all("Иванов" not in callback for callback in callbacks)
    assert "← Предыдущая" in callbacks.values()
    assert "Следующая →" in callbacks.values()
    assert "🔎 Новый поиск" in callbacks.values()
