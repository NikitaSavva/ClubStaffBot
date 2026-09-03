from aiogram.fsm.state import State, StatesGroup


class SubscriptionCorrectionStates(StatesGroup):
    viewing = State()
    editing = State()
    waiting_for_remaining_visits = State()
    waiting_for_expires_at = State()
    choosing_status = State()
    confirming = State()
