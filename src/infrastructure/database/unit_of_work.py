from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.integrity_errors import translate_integrity_error


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session.in_transaction():
            await self._session.rollback()

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            translated = translate_integrity_error(error)
            if translated is error:
                raise
            raise translated from error

    async def flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            translated = translate_integrity_error(error)
            if translated is error:
                raise
            raise translated from error
