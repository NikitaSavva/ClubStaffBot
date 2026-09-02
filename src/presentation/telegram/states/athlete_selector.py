from aiogram.fsm.state import State, StatesGroup


class AthleteSelectorStates(StatesGroup):
    selecting = State()
    waiting_for_query = State()
