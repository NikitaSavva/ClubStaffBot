from sqlalchemy.exc import IntegrityError

from application.attendance import AttendanceAlreadyExistsError
from infrastructure.database.integrity_errors import translate_integrity_error


class UniqueViolation(Exception):
    sqlstate = "23505"
    constraint_name = "uq_attendances_training_session_id"


def test_attendance_unique_violation_maps_to_controlled_error() -> None:
    error = IntegrityError("INSERT", {}, UniqueViolation())

    translated = translate_integrity_error(error)

    assert isinstance(translated, AttendanceAlreadyExistsError)
