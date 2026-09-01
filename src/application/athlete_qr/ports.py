from typing import Protocol
from uuid import UUID


class AthleteQrTokenCodec(Protocol):
    def issue(self, athlete_public_id: UUID) -> str: ...

    def verify(self, token: str) -> UUID: ...
