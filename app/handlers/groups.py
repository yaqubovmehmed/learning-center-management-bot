"""Patoklar (guruhlar): ro'yxat, karta, yaratish, tahrirlash."""
from __future__ import annotations

from datetime import date
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import groups, permissions, teachers
from app.states import GroupAdd, GroupEdit
from app.utils import (
    ALL_DAYS, clean_text, esc, fmt_date, format_days, money, paginate, parse_time,
    safe_int, status_label, today_str,
)
from config import settings

router = Router(name="groups")

COURSES = {
    "ielts": "IELTS",
    "general": "General English",
    "kids": "Kids English",
    "cefr": "CEFR",
    "business": "Business English",
    "other": "Boshqa",
}
LEVELS = {
    "beginner": "Beginner",
    "elementary": "Elementary",
    "pre": "Pre-Intermediate",
    "inter": "Intermediate",
    "upper": "Upper-Intermediate",
    "advanced": "Advanced",
    "ielts": "IELTS",
}


def _course_label(value: str | None) -> str:
    return value or "—"


def _level_label(value: str | None) -> str:
    return value or "—"


async def group_card(db: Database, group_id: int) -> tuple[str, Any]:
    group = await groups.get_group(db, group_id)
    if not group:
        return "❌ Patok topilmadi.", kb.ikb([kb.nav_row("grp:l:1")])
    text = (
        f"🗂 <b>{esc(group['name'])}</b>\n"
        f"📌 Holat: <b>{status_label(group['status'])}</b>\n\n"
        f"📚 Kurs: {esc(_course_label(group['course']))}\n"
        f"🎯 Daraja: {esc(_level_label(group['level']))}\n"
        f"👨‍🏫 O'qituvchi: {esc(group.get('teacher_name') or '— biriktirilmagan')}\n"
        f"📅 Kunlar: {esc(format_days(group['days']))}\n"
        f"🕒 Vaqt: {esc(group.get('time') or '—')} · ⏱ {group['duration_min']} daq\n"
        f"🚪 Xona: {esc(group.get('room') or '—')}\n"
        f"💰 To'lov: {esc(money(group.get('monthly_fee')))}\n"
        f"📆 Boshlanish: {esc(fmt_date(group.get('start_date')))}\n"
        f"👥 O'quvchilar: <b>{group.get('students_count', 0)}</b>"
    )
    rows = [
        [("👥 O'quvchilar", f"grp:students:{group_id}"), ("✅ Davomat", f"grp:att:{group_id}")],
        [("📝 Testlar", f"grp:tests:{group_id}"), ("✏️ Tahrirlash", f"grp:edit:{group_id}")],
    ]
    if group["status"] == "active":
        rows.append([("🗄 Arxivga olish", f"grp:arch:{group_id}")])
    else:
        rows.append([("♻️ Tiklash", f"grp:restore:{group_id}")])
    rows.append(kb.nav_row("grp:l:1"))
    return text, kb.ikb(rows)


async def _list_groups(event: Message | CallbackQuery, db: Database, user: dict, page: int, show_archived: bool = False) -> None:
    teacher = await permissions.teacher_profile(db, user) if user["role"] == "teacher" else None
    items = await groups.list_groups(
        db,
        teacher_id=teacher["id"] if teacher else None,
        include_archived=show_archived,
    )
    chunk, page, pages, total = paginate(items, page, 8)
    title = "🗂 <b>Patoklar</b>" if permissions.is_admin(user) else "🗂 <b>Guruhlarim</b>"
    text = f"{title}\n\nJami: <b>{total}</b>\n"
    if not items:
        text += "\nHozircha patok yo'q." if permissions.is_admin(user) else "\nSizga hali guruh biriktirilmagan."
    for group in chunk:
        teacher_label = group.get("teacher_name") or "o'qituvchisiz"
        text += (
            f"\n• <b>{esc(group['name'])}</b> — {group['students_count']} ta"
            f" · {esc(teacher_label)}"
        )
    rows: list[list[tuple[str, str]]] = []
    for group in chunk:
        icon = "🟢" if group["status"] == "active" else "⚪️"
        rows.append([(f"{icon} {group['name']}"[:55], f"grp:v:{group['id']}")])
    pages_row = kb.pager("grp:l" if not show_archived else "grp:la", page, pages)
    if pages_row:
        rows.append(pages_row)
    if permissions.is_admin(user):
        rows.append([("➕ Yangi patok", "grp:add")])
        rows.append([("🗄 Arxiv" if not show_archived else "🟢 Faollar", "grp:la:1" if not show_archived else "grp:l:1")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(F.text.in_({"🗂 Patoklar", "🗂 Guruhlarim"}))
async def groups_menu(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    await _list_groups(message, db, user, 1)


@router.callback_query(F.data.startswith("grp:l:"))
async def groups_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await _list_groups(callback, db, user, page)
    await callback.answer()


@router.callback_query(F.data.startswith("grp:la:"))
async def groups_archived(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await _list_groups(callback, db, user, page, show_archived=True)
    await callback.answer()


@router.callback_query(F.data.startswith("grp:v:"))
async def group_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("grp:students:"))
async def group_students(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    from app.handlers.students import show_student_list

    await show_student_list(callback, db, user, page=1, group_id=group_id)
    await callback.answer()


@router.callback_query(F.data.startswith("grp:att:"))
async def group_attendance(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    from app.handlers.attendance import show_attendance

    await show_attendance(callback, db, user, group_id, today_str(settings.tz))
    await callback.answer()


@router.callback_query(F.data.startswith("grp:tests:"))
async def group_tests(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    from app.handlers.tests import show_test_list

    await show_test_list(callback, db, user, page=1, group_id=group_id)
    await callback.answer()


@router.callback_query(F.data.startswith("grp:arch:"))
async def group_archive_prompt(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await ui.send(
        callback,
        f"🗄 <b>{esc(group['name'])}</b> arxivga olinsinmi?\n\n"
        "O'quvchilar va tarix saqlanadi, lekin patok faollar ro'yxatidan chiqadi.",
        kb.confirm_kb(f"grp:archyes:{group_id}", f"grp:v:{group_id}", "🗄 Ha, arxivga olish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grp:archyes:"))
async def group_archive(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    group = await groups.get_group(db, group_id)
    if group:
        await groups.archive_group(db, group_id)
        await audit(db, user, "group_archive", "group", group_id, {"name": group["name"]})
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Arxivlandi")


@router.callback_query(F.data.startswith("grp:restore:"))
async def group_restore(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    await groups.restore_group(db, group_id)
    await audit(db, user, "group_restore", "group", group_id)
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Tiklandi")


# ---------- Yaratish ----------

@router.callback_query(F.data == "grp:add")
async def group_add_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await state.clear()
    await state.set_state(GroupAdd.name)
    await ui.send(
        callback,
        "➕ <b>Yangi patok</b>\n\n1/8 — Patok nomini kiriting.\n"
        "Masalan: <code>IELTS 7.0 — kechki A</code>",
        kb.ikb([kb.nav_row("grp:l:1")]),
    )
    await callback.answer()


@router.message(GroupAdd.name)
async def group_add_name(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    name = clean_text(message.text or "", 50)
    if len(name) < 2 or "<" in name or ">" in name or "http" in name.lower():
        await message.answer("❌ Nom 2-50 belgi bo'lsin, havola va maxsus belgilarsiz.")
        return
    if await groups.group_name_taken(db, name):
        await message.answer("❌ Bu nomdagi patok allaqachon bor. Boshqa nom kiriting.")
        return
    await state.update_data(name=name)
    await state.set_state(GroupAdd.course)
    rows = [[(label, f"grp:a:course:{code}")] for code, label in COURSES.items()]
    rows.append(kb.nav_row("grp:l:1"))
    await message.answer("2/8 — Kursni tanlang:", reply_markup=kb.ikb(rows))


@router.callback_query(GroupAdd.course, F.data.startswith("grp:a:course:"))
async def group_add_course(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":")[3]
    await state.update_data(course=COURSES.get(code, "Boshqa"))
    await state.set_state(GroupAdd.level)
    rows = [[(label, f"grp:a:level:{code}")] for code, label in LEVELS.items()]
    rows.append(kb.nav_row("grp:l:1"))
    await ui.send(callback, "3/8 — Darajani tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(GroupAdd.level, F.data.startswith("grp:a:level:"))
async def group_add_level(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    code = callback.data.split(":")[3]
    await state.update_data(level=LEVELS.get(code, code))
    rows: list[list[tuple[str, str]]] = []
    for teacher in await teachers.list_teachers(db):
        rows.append([(teacher["name"][:55], f"grp:a:teacher:{teacher['id']}")])
    rows.append([("⏭ Keyinroq biriktirish", "grp:a:teacher:0")])
    rows.append(kb.nav_row("grp:l:1"))
    await state.set_state(GroupAdd.teacher)
    await ui.send(callback, "4/8 — O'qituvchini tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(GroupAdd.teacher, F.data.startswith("grp:a:teacher:"))
async def group_add_teacher(callback: CallbackQuery, state: FSMContext) -> None:
    teacher_id = safe_int(callback.data.split(":")[3])
    await state.update_data(teacher_id=teacher_id or None, days=[])
    await state.set_state(GroupAdd.days)
    await _days_keyboard(callback, [], "grp:a:day", "grp:a:daysdone")
    await callback.answer()


async def _days_keyboard(event: CallbackQuery | Message, selected: list[str], toggle_prefix: str, done_cb: str) -> None:
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for day in ALL_DAYS:
        label = ("✅ " if day in selected else "") + day.upper()
        row.append((label, f"{toggle_prefix}:{day}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("✅ Tayyor", done_cb)])
    await ui.send(event, "5/8 — Dars kunlarini tanlang:", kb.ikb(rows))


@router.callback_query(GroupAdd.days, F.data.startswith("grp:a:day:"))
async def group_add_day(callback: CallbackQuery, state: FSMContext) -> None:
    day = callback.data.split(":")[3]
    data = await state.get_data()
    selected = list(data.get("days") or [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    await state.update_data(days=selected)
    await _days_keyboard(callback, selected, "grp:a:day", "grp:a:daysdone")
    await callback.answer()


@router.callback_query(GroupAdd.days, F.data == "grp:a:daysdone")
async def group_add_days_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("days"):
        await callback.answer("Kamida bitta kun tanlang", show_alert=True)
        return
    await state.set_state(GroupAdd.time)
    await ui.send(
        callback,
        "6/8 — Dars vaqti (HH:MM), masalan <code>18:00</code>.\nO'tkazib yuborish mumkin.",
        kb.skip_kb("grp:a:skip:time", "grp:l:1"),
    )
    await callback.answer()


@router.message(GroupAdd.time)
async def group_add_time(message: Message, state: FSMContext) -> None:
    value = parse_time(message.text or "")
    if not value:
        await message.answer("❌ Vaqt noto'g'ri. Format: <code>18:00</code>")
        return
    await state.update_data(time=value)
    await state.set_state(GroupAdd.room)
    await message.answer(
        "7/8 — Xona raqami yoki nomi (ixtiyoriy).",
        reply_markup=kb.skip_kb("grp:a:skip:room", "grp:l:1"),
    )


@router.callback_query(GroupAdd.time, F.data == "grp:a:skip:time")
async def group_add_skip_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(time=None)
    await state.set_state(GroupAdd.room)
    await ui.send(callback, "7/8 — Xona raqami yoki nomi (ixtiyoriy).", kb.skip_kb("grp:a:skip:room", "grp:l:1"))
    await callback.answer()


@router.message(GroupAdd.room)
async def group_add_room(message: Message, state: FSMContext) -> None:
    room = clean_text(message.text or "", 30)
    await state.update_data(room=room or None)
    await state.set_state(GroupAdd.fee)
    await message.answer(
        "8/8 — Oylik to'lov (so'mda, faqat raqam). Masalan: <code>600000</code>",
        reply_markup=kb.skip_kb("grp:a:skip:fee", "grp:l:1"),
    )


@router.callback_query(GroupAdd.room, F.data == "grp:a:skip:room")
async def group_add_skip_room(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(room=None)
    await state.set_state(GroupAdd.fee)
    await ui.send(
        callback,
        "8/8 — Oylik to'lov (so'mda, faqat raqam). Masalan: <code>600000</code>",
        kb.skip_kb("grp:a:skip:fee", "grp:l:1"),
    )
    await callback.answer()


@router.message(GroupAdd.fee)
async def group_add_fee(message: Message, state: FSMContext, db: Database) -> None:
    fee = safe_int((message.text or "").replace(" ", "").replace(",", ""), 0, 0, 100_000_000)
    if fee <= 0:
        await message.answer("❌ To'lov noto'g'ri. Faqat raqam kiriting yoki o'tkazib yuboring.")
        return
    await state.update_data(monthly_fee=fee)
    await state.set_state(GroupAdd.confirm)
    await _group_add_summary(message, state, db)


@router.callback_query(F.data == "grp:a:skip:fee")
async def group_add_skip_fee(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.update_data(monthly_fee=None)
    await state.set_state(GroupAdd.confirm)
    await _group_add_summary(callback, state, db)
    await callback.answer()


async def _group_add_summary(event: Message | CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    teacher_name = None
    if data.get("teacher_id"):
        teacher = await teachers.get_teacher(db, int(data["teacher_id"]))
        teacher_name = teacher["name"] if teacher else None
    text = (
        "✅ <b>Tekshiring</b>\n\n"
        f"🗂 {esc(data.get('name'))}\n"
        f"📚 {esc(data.get('course') or '—')} · {esc(data.get('level') or '—')}\n"
        f"👨‍🏫 {esc(teacher_name or '— biriktirilmagan')}\n"
        f"📅 {esc(format_days(','.join(data.get('days') or [])))}\n"
        f"🕒 {esc(data.get('time') or '—')} · 🚪 {esc(data.get('room') or '—')}\n"
        f"💰 {esc(money(data.get('monthly_fee')))}"
    )
    await ui.send(event, text, kb.ikb([
        [("✅ Yaratish", "grp:a:confirm")],
        kb.nav_row("grp:l:1"),
    ]))


@router.callback_query(GroupAdd.confirm, F.data == "grp:a:confirm")
async def group_add_confirm(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    name = data.get("name")
    if not name:
        await callback.answer("Ma'lumot yo'q", show_alert=True)
        return
    if await groups.group_name_taken(db, name):
        await callback.answer("Bu nom band", show_alert=True)
        return
    group_id = await groups.create_group(db, {
        "name": name,
        "course": data.get("course"),
        "level": data.get("level"),
        "teacher_id": data.get("teacher_id"),
        "days": ",".join(data.get("days") or []),
        "time": data.get("time"),
        "room": data.get("room"),
        "monthly_fee": data.get("monthly_fee"),
        "start_date": today_str(settings.tz),
    })
    await audit(db, user, "group_create", "group", group_id, {"name": name})
    await state.clear()
    text, markup = await group_card(db, group_id)
    await ui.send(callback, "✅ Patok yaratildi!\n\n" + text, markup)
    await callback.answer("Yaratildi")


# ---------- Tahrirlash ----------

@router.callback_query(F.data.startswith("grp:edit:"))
async def group_edit_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    await ui.send(
        callback,
        "✏️ <b>Qaysi maydonni tahrirlaysiz?</b>",
        kb.ikb([
            [("Nom", f"grp:ed:{group_id}:name"), ("Kurs", f"grp:ed:{group_id}:course")],
            [("Daraja", f"grp:ed:{group_id}:level"), ("O'qituvchi", f"grp:teacher:{group_id}")],
            [("Kunlar", f"grp:edays:{group_id}"), ("Vaqt", f"grp:ed:{group_id}:time")],
            [("Xona", f"grp:ed:{group_id}:room"), ("To'lov", f"grp:ed:{group_id}:fee")],
            kb.nav_row(f"grp:v:{group_id}"),
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grp:ed:"))
async def group_edit_field(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, group_id_s, field = callback.data.split(":")
    group_id = safe_int(group_id_s)
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    if field == "course":
        await ui.send(callback, "Kursni tanlang:", kb.ikb(
            [[(label, f"grp:setc:{group_id}:{code}")] for code, label in COURSES.items()]
            + [kb.nav_row(f"grp:edit:{group_id}")]
        ))
        await callback.answer()
        return
    if field == "level":
        await ui.send(callback, "Darajani tanlang:", kb.ikb(
            [[(label, f"grp:setl:{group_id}:{code}")] for code, label in LEVELS.items()]
            + [kb.nav_row(f"grp:edit:{group_id}")]
        ))
        await callback.answer()
        return
    prompts = {
        "name": "Yangi nomni kiriting:",
        "time": "Yangi vaqt (HH:MM):",
        "room": "Yangi xona:",
        "fee": "Yangi oylik to'lov (so'm, faqat raqam):",
    }
    if field not in prompts:
        await callback.answer("Noto'g'ri maydon", show_alert=True)
        return
    await state.clear()
    await state.set_state(GroupEdit.value)
    await state.update_data(group_id=group_id, field=field)
    await ui.send(callback, prompts[field], kb.ikb([kb.nav_row(f"grp:edit:{group_id}")]))
    await callback.answer()


@router.callback_query(F.data.startswith("grp:setc:"))
async def group_set_course(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, group_id_s, code = callback.data.split(":")
    group_id = safe_int(group_id_s)
    await groups.update_group(db, group_id, course=COURSES.get(code, "Boshqa"))
    await state.clear()
    await audit(db, user, "group_edit", "group", group_id, {"field": "course"})
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Saqlandi")


@router.callback_query(F.data.startswith("grp:setl:"))
async def group_set_level(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, group_id_s, code = callback.data.split(":")
    group_id = safe_int(group_id_s)
    await groups.update_group(db, group_id, level=LEVELS.get(code, code))
    await state.clear()
    await audit(db, user, "group_edit", "group", group_id, {"field": "level"})
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Saqlandi")


@router.message(GroupEdit.value)
async def group_edit_value(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    group_id = int(data.get("group_id") or 0)
    field = data.get("field")
    raw = clean_text(message.text or "", 80)
    value: Any
    if field == "name":
        value = raw
        if len(value) < 2 or "<" in value or ">" in value or await groups.group_name_taken(db, value, group_id):
            await message.answer("❌ Nom noto'g'ri yoki band.")
            return
    elif field == "time":
        value = parse_time(raw)
        if not value:
            await message.answer("❌ Vaqt noto'g'ri. Format: 18:00")
            return
    elif field == "room":
        value = raw or None
    elif field == "fee":
        value = safe_int(raw.replace(" ", ""), 0, 0, 100_000_000) or None
    else:
        await state.clear()
        return
    await groups.update_group(db, group_id, **{field: value})
    await state.clear()
    await audit(db, user, "group_edit", "group", group_id, {"field": field})
    text, markup = await group_card(db, group_id)
    await message.answer("✅ Saqlandi.")
    await ui.send(message, text, markup)


@router.callback_query(F.data.startswith("grp:teacher:"))
async def group_teacher_pick(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    rows: list[list[tuple[str, str]]] = []
    for teacher in await teachers.list_teachers(db):
        rows.append([(teacher["name"][:55], f"grp:teach:{group_id}:{teacher['id']}")])
    rows.append([("🚫 Biriktirmaslik", f"grp:teach:{group_id}:0")])
    rows.append(kb.nav_row(f"grp:edit:{group_id}"))
    await ui.send(callback, "👨‍🏫 O'qituvchini tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("grp:teach:"))
async def group_teacher_set(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, group_id_s, teacher_s = callback.data.split(":")
    group_id = safe_int(group_id_s)
    teacher_id = safe_int(teacher_s) or None
    if teacher_id:
        teacher = await teachers.get_teacher(db, teacher_id)
        if not teacher or not teacher["is_active"]:
            await callback.answer("O'qituvchi faol emas", show_alert=True)
            return
    await groups.update_group(db, group_id, teacher_id=teacher_id)
    await audit(db, user, "group_teacher", "group", group_id, {"teacher_id": teacher_id})
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Saqlandi")


@router.callback_query(F.data.startswith("grp:edays:"))
async def group_edit_days(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    selected = [d for d in (group["days"] or "").split(",") if d]
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for day in ALL_DAYS:
        row.append((("✅ " if day in selected else "") + day.upper(), f"grp:edtoggle:{group_id}:{day}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("✅ Saqlash", f"grp:edonedays:{group_id}")])
    rows.append(kb.nav_row(f"grp:edit:{group_id}"))
    await ui.send(callback, "📅 Dars kunlarini tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("grp:edtoggle:"))
async def group_edit_days_toggle(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, group_id_s, day = callback.data.split(":")
    if day not in ALL_DAYS:
        await callback.answer("Noto'g'ri kun", show_alert=True)
        return
    group_id = safe_int(group_id_s)
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    selected = [d for d in (group["days"] or "").split(",") if d]
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    await groups.update_group(db, group_id, days=",".join(selected))
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for d in ALL_DAYS:
        row.append((("✅ " if d in selected else "") + d.upper(), f"grp:edtoggle:{group_id}:{d}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("✅ Saqlash", f"grp:edonedays:{group_id}")])
    rows.append(kb.nav_row(f"grp:edit:{group_id}"))
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=kb.ikb(rows))
        except Exception:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("grp:edonedays:"))
async def group_edit_days_done(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    await audit(db, user, "group_edit", "group", group_id, {"field": "days"})
    text, markup = await group_card(db, group_id)
    await ui.send(callback, text, markup)
    await callback.answer("Saqlandi")
