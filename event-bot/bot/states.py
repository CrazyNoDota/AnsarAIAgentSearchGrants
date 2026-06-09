from aiogram.fsm.state import State, StatesGroup


class ProfileSetup(StatesGroup):
    collecting = State()   # iterating over PROFILE_FIELDS


class Registration(StatesGroup):
    waiting_field_answer = State()   # waiting for user to answer an unknown field
    waiting_confirm = State()        # waiting for confirm/cancel before submit


class EditProfile(StatesGroup):
    choosing_field = State()
    entering_value = State()
