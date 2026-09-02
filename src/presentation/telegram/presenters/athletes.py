from application.athletes import AthleteSelectionItem
from application.identity import UnlinkedAthlete


def format_athlete_label(athlete: AthleteSelectionItem) -> str:
    if athlete.birth_date is None:
        return athlete.full_name
    return f"{athlete.full_name} ({athlete.birth_date:%d.%m.%Y})"


def format_athlete_account_link_label(athlete: UnlinkedAthlete) -> str:
    if athlete.birth_date is None:
        return athlete.full_name
    return f"{athlete.full_name} ({athlete.birth_date:%d.%m.%Y})"
