from application.athlete_qr.dto import GetAthleteQrTokenResult
from application.athlete_qr.ports import AthleteQrTokenCodec
from application.athlete_qr.queries import GetAthleteQrTokenQuery
from application.identity.authorization import require_athlete_actor
from application.identity.errors import AthleteProfileNotFoundError
from application.identity.ports import (
    AthleteRepository,
    RoleRepository,
    UserRepository,
)


class GetAthleteQrTokenInteractor:
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
        query: GetAthleteQrTokenQuery,
    ) -> GetAthleteQrTokenResult:
        actor = await require_athlete_actor(
            telegram_id=query.actor_telegram_id,
            users=self._users,
            roles=self._roles,
        )
        if actor.id is None:
            raise RuntimeError("A persisted User must have an id")

        athlete = await self._athletes.get_by_user_id(actor.id)
        if athlete is None:
            raise AthleteProfileNotFoundError

        return GetAthleteQrTokenResult(
            token=self._token_codec.issue(athlete.athlete_public_id)
        )
