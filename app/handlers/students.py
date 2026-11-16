"""O'quvchilar: ro'yxat, qidiruv, karta, qo'shish, tahrirlash, ota-ona."""
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
from app.services import attendance, groups, notifications, permissions, students, tests
from app.states import ParentAdd, Search, StudentAdd, StudentEdit
from app.utils import (
    clean_text, esc, fmt_date, fmt_phone, normalize_phone, paginate, safe_int,
    status_label, today_str, trend, validate_name,
)
from config import settings

router = Router(name="students")


async def _scope_teacher_id(db: Database, user: dict) -> int | None:
    if permissions.is_admin(user):
        return None
    teacher = await permissions.teacher_profile(db, user)
    return teacher["id"] if teacher else -1


def _student_icon(status: str) -> str:
    return {"active": "🟢", "frozen": "🧊", "left": "⚪️"}.get(status, "⚪️")


async def show_student_list(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    *,
    page: int = 1,
    group_id: int | None = None,
    all_statuses: bool = False,
) -> None:
    teacher_id = await _scope_teacher_id(db, user)
    if group_id is not None and not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(event)
        return
    if teacher_id == -1:
        await ui.deny(event)
        return
    items = await students.list_students(
        db,
        group_id=group_id,
        teacher_id=teacher_id,
        status=None if all_statuses else "active",
        limit=500,
    )
    chunk, page, pages, total = paginate(items, page, 8)
    title = "👥 <b>O'quvchilar</b>" if permissions.is_admin(user) else "👥 <b>O'quvchilarim</b>"
    text = f"{title}\n\nJami: <b>{total}</b>"
    if group_id:
        group = await groups.get_group(db, group_id)
        text += f" · 🗂 <b>{esc(group['name'] if group else '—')}</b>"
    if not items:
        text += "\n\nHozircha o'quvchi yo'q."
    rows: list[list[tuple[str, str]]] = []
    for student in chunk:
        label = f"{_student_icon(student['status'])} {student['full_name']}"
        if student.get("group_name"):
            label += f" · {student['group_name']}"
        rows.append([(label[:60], f"stu:v:{student['id']}")])
    if pages > 1:
        if group_id:
            prefix = f"stu:ga:{group_id}" if all_statuses else f"stu:g:{group_id}"
        else:
            prefix = "stu:all" if all_statuses else "stu:l"
        rows.append(kb.pager(prefix, page, pages))
    rows.append([("🔎 Qidirish", "stu:search")])
    if permissions.is_admin(user):
        rows.append([("➕ Yangi o'quvchi", "stu:add")])
    toggle = "🟢 Faollar" if all_statuses else "📋 Barchasi"
    if group_id:
        toggle_cb = f"stu:g:{group_id}:1" if all_statuses else f"stu:ga:{group_id}:1"
    else:
        toggle_cb = "stu:l:1" if all_statuses else "stu:all:1"
    rows.append([(toggle, toggle_cb)])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(F.text.in_({"👥 O'quvchilar", "👥 O'quvchilarim"}))
async def students_menu(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    await show_student_list(message, db, user, page=1)


@router.callback_query(F.data.startswith("stu:l:"))
async def students_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await show_student_list(callback, db, user, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("stu:all:"))
async def students_all(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await show_student_list(callback, db, user, page=page, all_statuses=True)
    await callback.answer()


@router.callback_query(F.data.startswith("stu:g:"))
async def students_group(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    group_id = safe_int(parts[2])
    page = safe_int(parts[3] if len(parts) > 3 else 1, 1, 1, 999)
    await show_student_list(callback, db, user, page=page, group_id=group_id)
    await callback.answer()


@router.callback_query(F.data.startswith("stu:ga:"))
async def students_group_all(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    group_id = safe_int(parts[2])
    page = safe_int(parts[3] if len(parts) > 3 else 1, 1, 1, 999)
    await show_student_list(callback, db, user, page=page, group_id=group_id, all_statuses=True)
    await callback.answer()


@router.callback_query(F.data.startswith("stu:v:"))
async def student_view(callback: CallbackQuery, db: Database, user: dict | None, bot_username: str) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    text, markup = await student_card(db, user, student_id, bot_username=bot_username)
    await ui.send(callback, text, markup)
    await callback.answer()


async def student_card(db: Database, user: dict, student_id: int, *, bot_username: str) -> tuple[str, Any]:
    student = await students.get_student(db, student_id)
    if not student:
        return "❌ O'quvchi topilmadi.", kb.ikb([kb.nav_row("stu:l:1")])
    parents = await students.parents_of_student(db, student_id)
    today = today_str(settings.tz)
    start = (date.fromisoformat(today).replace(day=1)).isoformat()
    att = await attendance.summary(db, student_id, start, today)
    latest = await tests.latest_for_student(db, student_id)
    admin = permissions.is_admin(user)
    text = (
        f"👤 <b>{esc(student['full_name'])}</b>\n"
        f"{_student_icon(student['status'])} Holat: <b>{status_label(student['status'])}</b>\n\n"
        f"🗂 Patok: {esc(student.get('group_name') or '— biriktirilmagan')}\n"
        f"👨‍🏫 O'qituvchi: {esc(student.get('teacher_name') or '—')}\n"
        f"📞 Telefon: {esc(fmt_phone(student.get('phone')))}\n"
        f"📅 Qo'shilgan: {esc(fmt_date(student.get('joined_at')))}\n"
        f"✅ Oy davomati: "
    )
    if att.get("rate") is None:
        text += "— (dars belgilanmagan)"
    else:
        text += f"<b>{att['rate']:.0f}%</b> ({att['present'] + att['late']}/{att['total'] - att['excused']})"
        if att["absent"]:
            text += f" · ❌ {att['absent']}"
        if att["late"]:
            text += f" · ⏰ {att['late']}"
    if latest:
        percent = (float(latest["score"]) / float(latest["max_score"]) * 100) if latest["max_score"] else 0
        text += f"\n📝 Oxirgi test: <b>{esc(latest['title'])}</b> — {percent:.0f}%"
    if student.get("notes"):
        text += f"\n📝 Izoh: {esc(student['notes'])}"
    text += "\n\n👨‍👩‍👧 <b>Ota-onalar:</b>"
    if not parents:
        text += "\n— biriktirilmagan"
    for parent in parents:
        linked = "✅ Telegram" if parent.get("tg_id") else "⚪️ ulanmagan"
        phone = fmt_phone(parent.get("phone")) if admin else "•••"
        text += f"\n• {esc(parent['full_name'])} — {esc(phone)} · {linked}"
    new_reports = await db.scalar(
        "SELECT COUNT(*) FROM absence_reports WHERE student_id=? AND status='new'", (student_id,)
    )
    if new_reports:
        text += f"\n\n📩 Yangi sabab xabarlari: <b>{int(new_reports)}</b>"

    rows: list[list[tuple[str, str]]] = [
        [("✅ Davomat tarixi", f"stu:att:{student_id}"), ("📊 Test natijalari", f"stu:tests:{student_id}")],
    ]
    if admin:
        rows.append([("✏️ Tahrirlash", f"stu:edit:{student_id}"), ("🔀 Guruhga o'tkazish", f"stu:transfer:{student_id}")])
        rows.append([("👨‍👩‍👧 Ota-onalar", f"stu:parent:{student_id}"), ("📌 Holat", f"stu:status:{student_id}")])
        for parent in parents:
            if not parent.get("tg_id"):
                rows.append([(f"🔗 {parent['full_name']} uchun havola"[:55], f"inv:send:parent:{parent['id']}")])
    rows.append(kb.nav_row("stu:l:1"))
    return text, kb.ikb(rows)


@router.callback_query(F.data.startswith("stu:att:"))
async def student_attendance_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    text = await student_attendance_text(db, student_id)
    await ui.send(callback, text, kb.ikb([kb.nav_row(f"stu:v:{student_id}")]))
    await callback.answer()


async def student_attendance_text(db: Database, student_id: int) -> str:
    student = await students.get_student(db, student_id)
    rows = await attendance.student_history(db, student_id, 15)
    text = f"✅ <b>{esc(student['full_name'] if student else '')}</b> — davomat tarixi\n\n"
    if not rows:
        return text + "Hozircha yozuv yo'q."
    for row in rows:
        icon = {"present": "✅", "absent": "❌", "late": "⏰", "excused": "📝"}.get(row["status"], "•")
        text += f"{icon} {esc(fmt_date(row['date']))} — {status_label(row['status'])}"
        if row.get("check_in"):
            text += f" · 🕒 {esc(row['check_in'])}"
            if row.get("check_out"):
                text += f"-{esc(row['check_out'])}"
        if row.get("minutes_late"):
            text += f" · +{row['minutes_late']} daq"
        text += "\n"
    return text


@router.callback_query(F.data.startswith("stu:tests:"))
async def student_tests_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    text = await student_tests_text(db, student_id)
    await ui.send(callback, text, kb.ikb([kb.nav_row(f"stu:v:{student_id}")]))
    await callback.answer()


async def student_tests_text(db: Database, student_id: int) -> str:
    student = await students.get_student(db, student_id)
    rows = await tests.results_for_student(db, student_id, 20)
    text = f"📊 <b>{esc(student['full_name'] if student else '')}</b> — test natijalari\n\n"
    if not rows:
        return text + "Hozircha natija yo'q."
    for row in rows:
        if row["is_absent"]:
            text += f"❌ {esc(fmt_date(row['date']))} · {esc(row['title'])} — qatnashmadi\n"
            continue
        percent = (float(row["score"]) / float(row["max_score"]) * 100) if row["max_score"] else 0
        text += f"📝 {esc(fmt_date(row['date']))} · {esc(row['title'])}: <b>{percent:.0f}%</b>"
        if row.get("band") is not None:
            text += f" · band {row['band']:.1f}"
        text += "\n"
    return text


# ---------- Qidiruv ----------

@router.callback_query(F.data == "stu:search")
async def student_search_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await state.clear()
    await state.set_state(Search.query)
    await ui.send(callback, "🔎 O'quvchining ismi yoki telefon raqamini kiriting:", kb.ikb([kb.nav_row("stu:l:1")]))
    await callback.answer()


@router.message(Search.query)
async def student_search(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    query = clean_text(message.text or "", 60)
    if len(query) < 2:
        await message.answer("❌ Kamida 2 belgi kiriting.")
        return
    teacher_id = await _scope_teacher_id(db, user)
    rows = await students.list_students(db, teacher_id=teacher_id, status=None, query=query, limit=15)
    await state.clear()
    text = f"🔎 <b>{esc(query)}</b> bo'yicha natijalar: <b>{len(rows)}</b>"
    if not rows:
        text += "\n\nTopilmadi. Boshqacha yozib ko'ring."
    markup_rows = [
        [(f"{_student_icon(s['status'])} {s['full_name']} · {s.get('group_name') or '—'}"[:58], f"stu:v:{s['id']}")]
        for s in rows
    ]
    markup_rows.append([("🔎 Qayta qidirish", "stu:search")])
    markup_rows.append(kb.nav_row("stu:l:1"))
    await message.answer(text, reply_markup=kb.ikb(markup_rows))


# ---------- Qo'shish ----------

@router.callback_query(F.data == "stu:add")
async def student_add_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await state.clear()
    await state.set_state(StudentAdd.name)
    await ui.send(
        callback,
        "➕ <b>Yangi o'quvchi</b>\n\n1/6 — O'quvchining to'liq ismini kiriting.\nMasalan: <code>Ali Valiyev</code>",
        kb.ikb([kb.nav_row("stu:l:1")]),
    )
    await callback.answer()


@router.message(StudentAdd.name)
async def student_add_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text or "")
    if not name:
        await message.answer("❌ Ism noto'g'ri. 2-80 belgi, faqat harflar va bo'sh joy.")
        return
    await state.update_data(name=name)
    await state.set_state(StudentAdd.phone)
    await message.answer(
        "2/6 — O'quvchi telefon raqami (ixtiyoriy).\nFormat: <code>+998 90 123 45 67</code>",
        reply_markup=kb.skip_kb("stu:a:skip:phone", "stu:l:1"),
    )


@router.message(StudentAdd.phone)
async def student_add_phone(message: Message, state: FSMContext, db: Database) -> None:
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer("❌ Telefon noto'g'ri. Format: +998 90 123 45 67")
        return
    await state.update_data(phone=phone)
    await state.set_state(StudentAdd.group)
    await _student_group_picker(message, db)


async def _student_group_picker(event: Message | CallbackQuery, db: Database) -> None:
    items = await groups.list_groups(db)
    rows: list[list[tuple[str, str]]] = [
        [(f"{g['name']} · {g['students_count']} ta"[:55], f"stu:a:group:{g['id']}")] for g in items
    ]
    rows.append([("⏭ Guruhsiz qo'shish", "stu:a:skip:group")])
    rows.append(kb.nav_row("stu:l:1"))
    await ui.send(event, "3/6 — Patokni tanlang:", kb.ikb(rows))


@router.callback_query(StudentAdd.phone, F.data == "stu:a:skip:phone")
async def student_add_skip_phone(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.update_data(phone=None)
    await state.set_state(StudentAdd.group)
    await _student_group_picker(callback, db)
    await callback.answer()


@router.callback_query(StudentAdd.group, F.data.startswith("stu:a:group:"))
async def student_add_group(callback: CallbackQuery, state: FSMContext) -> None:
    group_id = safe_int(callback.data.split(":")[3]) or None
    await state.update_data(group_id=group_id)
    await state.set_state(StudentAdd.parent_name)
    await ui.send(
        callback,
        "4/6 — Ota-onaning to'liq ismini kiriting.\n"
        "Keyin telegramda kuzatish uchun taklif havolasi beriladi. O'tkazib yuborish mumkin.",
        kb.skip_kb("stu:a:skip:parent", "stu:l:1"),
    )
    await callback.answer()


@router.callback_query(StudentAdd.group, F.data == "stu:a:skip:group")
async def student_add_skip_group(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(group_id=None)
    await state.set_state(StudentAdd.parent_name)
    await ui.send(
        callback,
        "4/6 — Ota-onaning to'liq ismini kiriting.\nO'tkazib yuborish mumkin.",
        kb.skip_kb("stu:a:skip:parent", "stu:l:1"),
    )
    await callback.answer()


@router.message(StudentAdd.parent_name)
async def student_add_parent_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text or "")
    if not name:
        await message.answer("❌ Ism noto'g'ri. 2-80 belgi.")
        return
    await state.update_data(parent_name=name)
    await state.set_state(StudentAdd.parent_phone)
    await message.answer("5/6 — Ota-onaning telefon raqamini kiriting. Format: <code>+998 90 123 45 67</code>")


@router.callback_query(StudentAdd.parent_name, F.data == "stu:a:skip:parent")
async def student_add_skip_parent(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.update_data(parent_name=None, parent_phone=None)
    await state.set_state(StudentAdd.confirm)
    await _student_add_summary(callback, state, db)
    await callback.answer()


@router.message(StudentAdd.parent_phone)
async def student_add_parent_phone(message: Message, state: FSMContext, db: Database) -> None:
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer("❌ Telefon noto'g'ri. Format: +998 90 123 45 67")
        return
    existing = await students.parent_by_phone(db, phone)
    await state.update_data(parent_phone=phone)
    await state.set_state(StudentAdd.confirm)
    if existing:
        await message.answer("ℹ️ Bu raqamli ota-ona bazada bor — mavjud profil ishlatiladi.")
    await _student_add_summary(message, state, db)


async def _student_add_summary(event: Message | CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    group_name = None
    if data.get("group_id"):
        group = await groups.get_group(db, int(data["group_id"]))
        group_name = group["name"] if group else None
    text = (
        "✅ <b>Tekshiring</b>\n\n"
        f"👤 {esc(data.get('name'))}\n"
        f"📞 {esc(fmt_phone(data.get('phone')))}\n"
        f"🗂 Patok: {esc(group_name or '— guruhsiz')}\n"
        f"👨‍👩‍👧 Ota-ona: {esc(data.get('parent_name') or '—')}\n"
        f"📞 Ota-ona tel: {esc(fmt_phone(data.get('parent_phone')))}\n\n"
        "Tasdiqlasangiz, o'quvchi bazaga qo'shiladi."
    )
    await ui.send(event, text, kb.ikb([
        [("✅ Qo'shish", "stu:a:confirm")],
        kb.nav_row("stu:l:1"),
    ]))


@router.callback_query(StudentAdd.confirm, F.data == "stu:a:confirm")
async def student_add_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    user: dict | None,
    bot_username: str,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    name = data.get("name")
    if not name:
        await callback.answer("Ma'lumot yo'q", show_alert=True)
        return
    if await students.student_name_taken(db, name, data.get("group_id")):
        await callback.answer("Bu ismli o'quvchi shu patokda bor.", show_alert=True)
        return
    student_id, parent_id = await students.create_student(
        db,
        full_name=name,
        phone=data.get("phone"),
        group_id=data.get("group_id"),
        created_by=int(user["id"]),
        parent_name=data.get("parent_name"),
        parent_phone=data.get("parent_phone"),
    )
    await audit(db, user, "student_create", "student", student_id, {
        "name": name, "group_id": data.get("group_id"), "parent_id": parent_id
    })
    await state.clear()
    text, markup = await student_card(db, user, student_id, bot_username=bot_username)
    await ui.send(callback, "✅ O'quvchi qo'shildi!\n\n" + text, markup)
    await callback.answer("Qo'shildi")
    if parent_id:
        from app.handlers.invite_admin import send_invite

        await send_invite(callback.message or callback, db, user, role="parent", target_id=parent_id, bot_username=bot_username)


# ---------- Tahrirlash ----------

@router.callback_query(F.data.startswith("stu:edit:"))
async def student_edit_menu(callback: CallbackQuery, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    await ui.send(
        callback,
        "✏️ <b>Qaysi maydonni tahrirlaysiz?</b>",
        kb.ikb([
            [("Ism", f"stu:ed:{student_id}:full_name"), ("Telefon", f"stu:ed:{student_id}:phone")],
            [("Tug'ilgan sana", f"stu:ed:{student_id}:birth_date"), ("Izoh", f"stu:ed:{student_id}:notes")],
            kb.nav_row(f"stu:v:{student_id}"),
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stu:ed:"))
async def student_edit_field(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, student_id_s, field = callback.data.split(":")
    if field not in ("full_name", "phone", "birth_date", "notes"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await state.clear()
    await state.set_state(StudentEdit.value)
    await state.update_data(student_id=safe_int(student_id_s), field=field)
    prompts = {
        "full_name": "Yangi ismni kiriting:",
        "phone": "Yangi telefon (yoki <code>yo'q</code>):",
        "birth_date": "Tug'ilgan sana (KK.OO.YYYY):",
        "notes": "Izoh kiriting:",
    }
    await ui.send(callback, prompts[field], kb.ikb([kb.nav_row(f"stu:v:{student_id_s}")]))
    await callback.answer()


@router.message(StudentEdit.value)
async def student_edit_value(message: Message, state: FSMContext, db: Database, user: dict | None, bot_username: str) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    student_id = int(data.get("student_id") or 0)
    field = data.get("field")
    raw = clean_text(message.text or "", 120)
    value: Any = raw
    if field == "full_name":
        value = validate_name(raw)
        if not value:
            await message.answer("❌ Ism noto'g'ri.")
            return
        student = await students.get_student(db, student_id)
        if student and await students.student_name_taken(db, value, student.get("group_id"), student_id):
            await message.answer("❌ Bu ismli o'quvchi patokda bor.")
            return
    elif field == "phone":
        value = None if raw.lower() in ("yo'q", "yoq", "-", "skip") else normalize_phone(raw)
        if raw.lower() not in ("yo'q", "yoq", "-", "skip") and not value:
            await message.answer("❌ Telefon noto'g'ri.")
            return
    elif field == "birth_date":
        from app.utils import parse_date

        value = parse_date(raw)
        if not value:
            await message.answer("❌ Sana noto'g'ri. Format: KK.OO.YYYY")
            return
    await students.update_student(db, student_id, **{field: value})
    await state.clear()
    await audit(db, user, "student_edit", "student", student_id, {"field": field})
    text, markup = await student_card(db, user, student_id, bot_username=bot_username)
    await message.answer("✅ Saqlandi.")
    await ui.send(message, text, markup)


# ---------- Guruhga o'tkazish ----------

@router.callback_query(F.data.startswith("stu:transfer:"))
async def student_transfer_pick(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    items = await groups.list_groups(db)
    rows: list[list[tuple[str, str]]] = [
        [(f"{g['name']} · {g['students_count']}"[:55], f"stu:tr:{student_id}:{g['id']}")] for g in items
    ]
    rows.append([("🚫 Guruhsiz", f"stu:tr:{student_id}:0")])
    rows.append(kb.nav_row(f"stu:v:{student_id}"))
    await ui.send(callback, "🔀 Yangi patokni tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("stu:tr:"))
async def student_transfer(callback: CallbackQuery, db: Database, user: dict | None, bot_username: str) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, student_id_s, group_id_s = callback.data.split(":")
    student_id = safe_int(student_id_s)
    group_id = safe_int(group_id_s) or None
    student = await students.get_student(db, student_id)
    if not student:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await students.update_student(db, student_id, group_id=group_id)
    await audit(db, user, "student_transfer", "student", student_id, {"from": student.get("group_id"), "to": group_id})
    text, markup = await student_card(db, user, student_id, bot_username=bot_username)
    await ui.send(callback, text, markup)
    await callback.answer("O'tkazildi")


# ---------- Holat ----------

@router.callback_query(F.data.startswith("stu:status:"))
async def student_status_menu(callback: CallbackQuery, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    await ui.send(
        callback,
        "📌 Yangi holatni tanlang:",
        kb.ikb([
            [("🟢 Faol", f"stu:st:{student_id}:active")],
            [("🧊 Muzlatilgan", f"stu:st:{student_id}:frozen")],
            [("⚪️ Chiqib ketgan", f"stu:st:{student_id}:left")],
            kb.nav_row(f"stu:v:{student_id}"),
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stu:st:"))
async def student_status_set(callback: CallbackQuery, db: Database, user: dict | None, bot_username: str) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, student_id_s, status = callback.data.split(":")
    if status not in ("active", "frozen", "left"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    student_id = safe_int(student_id_s)
    await students.set_status(db, student_id, status)
    await audit(db, user, "student_status", "student", student_id, {"status": status})
    text, markup = await student_card(db, user, student_id, bot_username=bot_username)
    await ui.send(callback, text, markup)
    await callback.answer("Saqlandi")


# ---------- Ota-onalar ----------

@router.callback_query(F.data.startswith("stu:parent:"))
async def student_parents(
    callback: CallbackQuery,
    db: Database,
    user: dict | None,
    *,
    answer_cb: bool = True,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    student = await students.get_student(db, student_id)
    if not student:
        await callback.answer("Topilmadi", show_alert=True)
        return
    parents = await students.parents_of_student(db, student_id)
    text = f"👨‍👩‍👧 <b>{esc(student['full_name'])}</b> — ota-onalar\n\n"
    if not parents:
        text += "Hozircha biriktirilmagan."
    for parent in parents:
        status = "✅ Telegram ulangan" if parent.get("tg_id") else "⚪️ havola yuborilmagan"
        text += f"• <b>{esc(parent['full_name'])}</b> — {esc(fmt_phone(parent.get('phone')))}\n  {status}\n"
    rows: list[list[tuple[str, str]]] = []
    for parent in parents:
        if not parent.get("tg_id"):
            rows.append([(f"🔗 {parent['full_name']} havola"[:55], f"inv:send:parent:{parent['id']}")])
        rows.append([(f"🗑 {parent['full_name']}ni ajratish"[:55], f"stu:unp:{student_id}:{parent['id']}")])
    rows.append([("➕ Ota-ona qo'shish", f"stu:padd:{student_id}")])
    rows.append(kb.nav_row(f"stu:v:{student_id}"))
    await ui.send(callback, text, kb.ikb(rows))
    if answer_cb:
        await callback.answer()


@router.callback_query(F.data.startswith("stu:unp:"))
async def student_parent_unlink_prompt(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, student_id_s, parent_id_s = callback.data.split(":")
    parent = await students.get_parent(db, safe_int(parent_id_s))
    await ui.send(
        callback,
        f"🗑 <b>{esc(parent['full_name'] if parent else '')}</b> o'quvchidan ajratilsinmi?\n"
        "Telegram akkaunt o'chirilmaydi, faqat bog'lanish uziladi.",
        kb.confirm_kb(f"stu:unpyes:{student_id_s}:{parent_id_s}", f"stu:parent:{student_id_s}", "🗑 Ha, ajratish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stu:unpyes:"))
async def student_parent_unlink(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, student_id_s, parent_id_s = callback.data.split(":")
    await students.unlink_parent(db, safe_int(student_id_s), safe_int(parent_id_s))
    await audit(db, user, "parent_unlink", "student", student_id_s, {"parent_id": parent_id_s})
    await callback.answer("Ajratildi")
    await student_parents(callback, db, user, answer_cb=False)


@router.callback_query(F.data.startswith("stu:padd:"))
async def parent_add_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    await state.clear()
    await state.set_state(ParentAdd.name)
    await state.update_data(student_id=student_id)
    await ui.send(callback, "➕ Ota-onaning to'liq ismini kiriting:", kb.ikb([kb.nav_row(f"stu:parent:{student_id}")]))
    await callback.answer()


@router.message(ParentAdd.name)
async def parent_add_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text or "")
    if not name:
        await message.answer("❌ Ism noto'g'ri.")
        return
    await state.update_data(parent_name=name)
    await state.set_state(ParentAdd.phone)
    await message.answer("Telefon raqamini kiriting. Format: <code>+998 90 123 45 67</code>")


@router.message(ParentAdd.phone)
async def parent_add_phone(
    message: Message,
    state: FSMContext,
    db: Database,
    user: dict | None,
    bot_username: str,
) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer("❌ Telefon noto'g'ri.")
        return
    data = await state.get_data()
    student_id = int(data.get("student_id") or 0)
    parent_name = data.get("parent_name")
    parent_id = await students.upsert_parent(db, parent_name, phone)
    await students.link_parent(db, student_id, parent_id)
    await audit(db, user, "parent_link", "student", student_id, {"parent_id": parent_id})
    await state.clear()
    await message.answer("✅ Ota-ona biriktirildi.")
    await student_parents_for_message(message, db, user, student_id)
    parent = await students.get_parent(db, parent_id)
    if parent and not parent.get("user_id"):
        from app.handlers.invite_admin import send_invite

        await send_invite(message, db, user, role="parent", target_id=parent_id, bot_username=bot_username)


async def student_parents_for_message(message: Message, db: Database, user: dict, student_id: int) -> None:
    student = await students.get_student(db, student_id)
    parents = await students.parents_of_student(db, student_id)
    text = f"👨‍👩‍👧 <b>{esc(student['full_name'] if student else '')}</b> — ota-onalar\n\n"
    for parent in parents:
        status = "✅ Telegram ulangan" if parent.get("tg_id") else "⚪️ havola yuborilmagan"
        text += f"• <b>{esc(parent['full_name'])}</b> — {esc(fmt_phone(parent.get('phone')))}\n  {status}\n"
    rows = [[("👨‍👩‍👧 Ota-onalar bo'limi", f"stu:parent:{student_id}")], kb.nav_row(f"stu:v:{student_id}")]
    await message.answer(text, reply_markup=kb.ikb(rows))
