from application.errors import ApplicationError


class AttendanceAlreadyExistsError(ApplicationError):
    """The Athlete already has Attendance for this TrainingSession."""
