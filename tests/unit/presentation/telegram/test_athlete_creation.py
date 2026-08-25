from datetime import date

import pytest

from presentation.telegram.handlers.athlete_creation import parse_birth_date


def test_birth_date_parser_accepts_dd_mm_yyyy() -> None:
    assert parse_birth_date("25.08.1993") == date(1993, 8, 25)


@pytest.mark.parametrize(
    "value",
    [
        "1993-08-25",
        "25/08/1993",
        "31.02.2000",
        "abc",
        "1.1.2000",
    ],
)
def test_birth_date_parser_rejects_invalid_format_or_calendar_date(
    value: str,
) -> None:
    assert parse_birth_date(value) is None
