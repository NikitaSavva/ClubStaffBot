from uuid import UUID

import pytest

from domain.identity import Athlete, AthleteFirstNameRequiredError


def test_manual_athlete_is_active_unlinked_and_has_uuid4() -> None:
    athlete = Athlete.create_manually(first_name="  Ирина  ")

    assert athlete.id is None
    assert isinstance(athlete.athlete_public_id, UUID)
    assert athlete.athlete_public_id.version == 4
    assert athlete.user_id is None
    assert athlete.first_name == "Ирина"
    assert athlete.last_name is None
    assert athlete.phone is None
    assert athlete.is_active


@pytest.mark.parametrize("first_name", ["", " ", "\n\t"])
def test_manual_athlete_requires_non_blank_first_name(
    first_name: str,
) -> None:
    with pytest.raises(AthleteFirstNameRequiredError):
        Athlete.create_manually(first_name=first_name)
