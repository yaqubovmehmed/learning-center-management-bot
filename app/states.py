"""FSM holatlari."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class LinkFlow(StatesGroup):
    phone = State()


class GroupAdd(StatesGroup):
    name = State()
    course = State()
    level = State()
    teacher = State()
    days = State()
    time = State()
    room = State()
    fee = State()
    confirm = State()


class GroupEdit(StatesGroup):
    value = State()


class StudentAdd(StatesGroup):
    name = State()
    phone = State()
    group = State()
    parent_name = State()
    parent_phone = State()
    confirm = State()


class StudentEdit(StatesGroup):
    value = State()


class ParentAdd(StatesGroup):
    name = State()
    phone = State()


class TeacherAdd(StatesGroup):
    name = State()
    phone = State()
    tg_id = State()


class TeacherEdit(StatesGroup):
    value = State()


class TestAdd(StatesGroup):
    group = State()
    title = State()
    kind = State()
    date = State()
    max_score = State()
    confirm = State()


class TestEntry(StatesGroup):
    score = State()


class Search(StatesGroup):
    query = State()


class Broadcast(StatesGroup):
    audience = State()
    text = State()
    confirm = State()


class ParentReason(StatesGroup):
    reason = State()


class SettingsEdit(StatesGroup):
    value = State()


class LessonTopic(StatesGroup):
    value = State()


class AttendanceNote(StatesGroup):
    value = State()
