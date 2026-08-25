from datetime import date

from application.identity import UnlinkedAthlete
from presentation.telegram.presenters.athletes import (
    format_athlete_account_link_label,
)


def test_account_link_label_contains_name_and_formatted_birth_date() -> None:
    athlete = UnlinkedAthlete(
        athlete_id=1,
        first_name="Иван",
        last_name="Иванов",
        birth_date=date(1993, 8, 25),
    )

    assert format_athlete_account_link_label(athlete) == (
        "Иван Иванов (25.08.1993)"
    )


def test_legacy_account_link_label_omits_missing_birth_date() -> None:
    athlete = UnlinkedAthlete(
        athlete_id=1,
        first_name="Иван",
        last_name="Иванов",
        birth_date=None,
    )

    assert format_athlete_account_link_label(athlete) == "Иван Иванов"
