"""Klaviaturalar: doimiy menyu va inline navigatsiya."""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Doimiy menyu matnlari (handlerlar shu konstantalarga tayanadi)
BTN_ADMIN = {
    "students": "👥 O'quvchilar",
    "groups": "🗂 Patoklar",
    "attendance": "✅ Davomat",
    "tests": "📝 Testlar",
    "reports": "📊 Hisobotlar",
    "teachers": "👨‍🏫 O'qituvchilar",
    "notifications": "🔔 Xabarlar",
    "settings": "⚙️ Sozlamalar",
    "audit": "🛡 Audit",
}
BTN_TEACHER = {
    "groups": "🗂 Guruhlarim",
    "attendance": "✅ Davomat",
    "tests": "📝 Testlar",
    "students": "👥 O'quvchilarim",
    "reports": "📊 Hisobot",
    "help": "☎️ Yordam",
}
BTN_PARENT = {
    "children": "👶 Farzandlarim",
    "attendance": "✅ Davomat",
    "results": "📊 Natijalar",
    "absence": "✉️ Sabab yuborish",
    "settings": "🔔 Sozlamalar",
    "contact": "☎️ Bog'lanish",
}


def main_menu(role: str) -> ReplyKeyboardMarkup:
    if role in ("superadmin", "admin"):
        rows = [
            [KeyboardButton(text=BTN_ADMIN["students"]), KeyboardButton(text=BTN_ADMIN["groups"])],
            [KeyboardButton(text=BTN_ADMIN["attendance"]), KeyboardButton(text=BTN_ADMIN["tests"])],
            [KeyboardButton(text=BTN_ADMIN["reports"]), KeyboardButton(text=BTN_ADMIN["teachers"])],
            [KeyboardButton(text=BTN_ADMIN["notifications"]), KeyboardButton(text=BTN_ADMIN["settings"])],
            [KeyboardButton(text=BTN_ADMIN["audit"])],
        ]
    elif role == "teacher":
        rows = [
            [KeyboardButton(text=BTN_TEACHER["groups"]), KeyboardButton(text=BTN_TEACHER["attendance"])],
            [KeyboardButton(text=BTN_TEACHER["tests"]), KeyboardButton(text=BTN_TEACHER["students"])],
            [KeyboardButton(text=BTN_TEACHER["reports"]), KeyboardButton(text=BTN_TEACHER["help"])],
        ]
    else:
        rows = [
            [KeyboardButton(text=BTN_PARENT["children"]), KeyboardButton(text=BTN_PARENT["attendance"])],
            [KeyboardButton(text=BTN_PARENT["results"]), KeyboardButton(text=BTN_PARENT["absence"])],
            [KeyboardButton(text=BTN_PARENT["settings"]), KeyboardButton(text=BTN_PARENT["contact"])],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def ikb(rows: Sequence[Sequence[tuple[str, str]]], **kwargs: Any) -> InlineKeyboardMarkup:
    """rows = [[(matn, callback), ...], ...]"""
    keyboard = [
        [InlineKeyboardButton(text=text, callback_data=cb) for text, cb in row]
        for row in rows
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard, **kwargs)


def nav_row(back_cb: str, home_cb: str = "home") -> list[tuple[str, str]]:
    return [("⬅️ Orqaga", back_cb), ("🏠 Bosh menyu", home_cb)]


def pager(prefix: str, page: int, pages: int) -> list[tuple[str, str]]:
    if pages <= 1:
        return []
    row: list[tuple[str, str]] = []
    if page > 1:
        row.append(("⬅️", f"{prefix}:{page - 1}"))
    row.append((f"{page}/{pages}", "noop"))
    if page < pages:
        row.append(("➡️", f"{prefix}:{page + 1}"))
    return row


def confirm_kb(yes_cb: str, no_cb: str = "home", yes_text: str = "✅ Ha, tasdiqlayman") -> InlineKeyboardMarkup:
    return ikb([[ (yes_text, yes_cb) ], [("❌ Bekor qilish", no_cb)]])


def invite_kb(url: str, revoke_cb: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔗 Havolani ochish", url=url)],
        [InlineKeyboardButton(text="📋 Havolani nusxalash", copy_text=CopyTextButton(text=url))],
    ]
    if revoke_cb:
        rows.append([InlineKeyboardButton(text="🚫 Havolani bekor qilish", callback_data=revoke_cb)])
    rows.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_kb(groups: Iterable[dict[str, Any]], prefix: str, back_cb: str = "home") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    for group in groups:
        title = f"{group['name']}"
        if group.get("students_count") is not None:
            title += f" · {group['students_count']} ta"
        rows.append([(title[:55], f"{prefix}:{group['id']}")])
    rows.append(nav_row(back_cb))
    return ikb(rows)


def students_kb(students: Iterable[dict[str, Any]], prefix: str, back_cb: str = "home") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    for student in students:
        icon = "🟢" if student.get("status", "active") == "active" else "⚪️"
        rows.append([(f"{icon} {student['full_name']}"[:58], f"{prefix}:{student['id']}")])
    rows.append(nav_row(back_cb))
    return ikb(rows)


def teachers_kb(teachers: Iterable[dict[str, Any]], prefix: str, back_cb: str = "home") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    for teacher in teachers:
        icon = "🟢" if teacher.get("is_active") else "⚪️"
        rows.append([(f"{icon} {teacher['name']}"[:58], f"{prefix}:{teacher['id']}")])
    rows.append(nav_row(back_cb))
    return ikb(rows)


def test_kinds_kb(prefix: str, back_cb: str) -> InlineKeyboardMarkup:
    return ikb([
        [("📝 Test", f"{prefix}:test"), ("🎯 Mock", f"{prefix}:mock")],
        [("⚡️ Quiz", f"{prefix}:quiz"), ("🎓 Imtihon", f"{prefix}:exam")],
        nav_row(back_cb),
    ])


def skip_kb(skip_cb: str, back_cb: str | None = None) -> InlineKeyboardMarkup:
    rows = [[("⏭ O'tkazib yuborish", skip_cb)]]
    if back_cb:
        rows.append([("⬅️ Orqaga", back_cb)])
    return ikb(rows)
