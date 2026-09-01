from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GetAthleteQrTokenResult:
    token: str
