from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.identity import SystemRoleCode
from infrastructure.database.models import RoleModel

SYSTEM_ROLES = (
    (SystemRoleCode.ATHLETE, "Athlete"),
    (SystemRoleCode.TRAINER, "Trainer"),
    (SystemRoleCode.ADMINISTRATOR, "Administrator"),
)


async def ensure_system_roles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    values = [
        {
            "code": code.value,
            "name": name,
            "is_system": True,
            "is_active": True,
        }
        for code, name in SYSTEM_ROLES
    ]
    statement = insert(RoleModel).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[RoleModel.code],
        set_={
            "name": statement.excluded.name,
            "is_system": True,
            "is_active": True,
        },
    )

    async with session_factory.begin() as session:
        await session.execute(statement)
