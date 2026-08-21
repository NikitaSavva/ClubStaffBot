from aiogram.fsm.state import State, StatesGroup


class CreateAthleteStates(StatesGroup):
    waiting_for_first_name = State()
