from aiogram.fsm.state import State, StatesGroup


class RoleManagementStates(StatesGroup):
    waiting_for_query = State()
    waiting_for_user_selection = State()
    viewing_user = State()
    waiting_for_role_selection = State()
    waiting_for_role_removal_selection = State()
