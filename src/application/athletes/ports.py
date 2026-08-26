from typing import Protocol

from application.athletes.dto import AthleteSummary


class AthleteReader(Protocol):
    async def list_all(self) -> tuple[AthleteSummary, ...]: ...
