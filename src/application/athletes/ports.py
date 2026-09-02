from typing import Protocol

from application.athletes.dto import AthleteSearch, AthleteSelectionItem


class AthleteSelectionReader(Protocol):
    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        search: AthleteSearch | None,
    ) -> tuple[AthleteSelectionItem, ...]: ...

    async def get_by_id(
        self,
        athlete_id: int,
    ) -> AthleteSelectionItem | None: ...
