from aiogram.fsm.state import State, StatesGroup


class TrainerAssignmentStates(StatesGroup):
    selecting_group = State()
    viewing_assigned_group = State()
    selecting_trainer = State()
    confirming = State()
