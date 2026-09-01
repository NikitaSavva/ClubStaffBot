from application.athlete_qr import AthleteQrTokenCodec
from application.identity.authorization import require_administrative_actor
from application.identity.errors import AthleteNotFoundError
from application.identity.ports import (
    AthleteRepository,
    RoleRepository,
    UserRepository,
)
from application.scanner.dto import ResolveAthleteQrResult
from application.scanner.queries import ResolveAthleteQrQuery


class ResolveAthleteQrInteractor:
    def __init__(
        self,
        user_repository: UserRepository,
        athlete_repository: AthleteRepository,
        role_repository: RoleRepository,
        token_codec: AthleteQrTokenCodec,
    ) -> None:
        self._users = user_repository
        self._athletes = athlete_repository
        self._roles = role_repository
        self._token_codec = token_codec

    async def __call__(
        self,
        query: ResolveAthleteQrQuery,
    ) -> ResolveAthleteQrResult:
        await require_administrative_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        athlete_public_id = self._token_codec.verify(
            query.athlete_qr_token
        )
        athlete = await self._athletes.get_by_public_id(athlete_public_id)
        if athlete is None:
            raise AthleteNotFoundError

        full_name = " ".join(
            part for part in (athlete.first_name, athlete.last_name) if part
        )
        return ResolveAthleteQrResult(
            full_name=full_name,
            birth_date=athlete.birth_date,
        )
