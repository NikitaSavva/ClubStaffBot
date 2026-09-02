from aiogram.fsm.state import State, StatesGroup


class ManualAttendanceStates(StatesGroup):
    selecting_session = State()
    confirming_session = State()
    terminal = State()
