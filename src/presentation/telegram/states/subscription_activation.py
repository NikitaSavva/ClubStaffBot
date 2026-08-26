from aiogram.fsm.state import State, StatesGroup


class SubscriptionActivationStates(StatesGroup):
    selecting_athlete = State()
    selecting_plan = State()
    selecting_group = State()
    confirming = State()
