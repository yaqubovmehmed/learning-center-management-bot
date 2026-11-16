"""Davomat: guruh tanlash, keldi/kelmadi, vaqt, ota-onalarga xabar."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.filters import RoleFilter
from app.security import audit
from app.services import attendance, groups, messages, notifications, permissions, settings as settings_service, students
from app.states import AttendanceNote, LessonTopic
from app.utils import add_days, clean_text, esc, fmt_date, fmt_date_long, paginate, safe_int, status_label, today_str
from config import settings

router = Router(name="attendance")

STATUS_ICON = {"present": "✅", "absent": "❌", "late": "⏰", "excused": "📝"}
CYCLE = {"present": "absent", "absent": "late", "late": "excused", "excused": "present"}


async def _local_time() -> str:
    return datetime.now(settings.tz).strftime("%H:%M")


async def _teacher_of_group(db: Database, group: dict) -> str | None:
    return group.get("teacher_name")


async def show_attendance(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    group_id: int,
    date_value: str,
    page: int = 1,
) -> None:
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(event)
        return
    group = await groups.get_group(db, group_id)
    if not group:
        await ui.toast(event, "Patok topilmadi", True)
        return
    lesson = await attendance.ensure_lesson(db, group_id, date_value, group.get("teacher_id"))
    entries = await attendance.lesson_entries(db, int(lesson["id"]))
    roster = await students.list_students(db, group_id=group_id, status="active", limit=300)
    chunk, page, pages, total = paginate(roster, page, 8)
    text = (
        f"✅ <b>Davomat</b> — {esc(group['name'])}\n"
        f"📅 {esc(fmt_date_long(date_value))}"
        + (f" · 📖 {esc(lesson['topic'])}" if lesson.get("topic") else "")
        + f"\n👥 O'quvchilar: <b>{total}</b>\n"
    )
    auto = await settings_service.get_bool(db, "auto_absence_notify", True)
    text += "🔔 Avtomatik xabar: " + ("yoqilgan" if auto else "o'chirilgan") + "\n\n"
    if not roster:
        text += "Bu patokda faol o'quvchi yo'q."
    rows: list[list[tuple[str, str]]] = []
    for student in chunk:
        entry = entries.get(int(student["id"]), {})
        status = entry.get("status", "present")
        icon = STATUS_ICON.get(status, "•")
        label = f"{icon} {student['full_name']}"
        rows.append([
            (label[:40], f"att:t:{lesson['id']}:{student['id']}:{page}"),
            ("🕒", f"att:time:{group_id}:{date_value}:{student['id']}:{page}"),
        ])
    if pages > 1:
        rows.append(kb.pager(f"att:g:{group_id}:{date_value}", page, pages))
    if roster:
        rows.append([("✅ Hammasi keldi", f"att:all:{group_id}:{date_value}")])
        rows.append([("💾 Saqlash", f"att:save:{lesson['id']}:{group_id}:{date_value}")])
    rows.append([
        ("⬅️ Kun", f"att:nav:{group_id}:{date_value}:-1"),
        ("📅 Bugun", f"att:g:{group_id}:{today_str(settings.tz)}:1"),
        ("➡️ Kun", f"att:nav:{group_id}:{date_value}:1"),
    ])
    rows.append([("📖 Mavzu", f"att:topic:{group_id}:{date_value}"), ("🕘 Tarix", f"att:hist:{group_id}")])
    rows.append(kb.nav_row(f"grp:v:{group_id}"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(RoleFilter("superadmin", "admin", "teacher"), F.text.in_({"✅ Davomat"}))
async def attendance_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    await _group_picker(message, db, user)


@router.callback_query(F.data == "att:menu")
async def attendance_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _group_picker(callback, db, user)
    await callback.answer()


async def _group_picker(event: Message | CallbackQuery, db: Database, user: dict) -> None:
    teacher = await permissions.teacher_profile(db, user) if user["role"] == "teacher" else None
    items = await groups.list_groups(db, teacher_id=teacher["id"] if teacher else None)
    today = today_str(settings.tz)
    stats_rows = await db.fetchall(
        "SELECT l.group_id, COUNT(a.id) AS total, "
        "SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) AS attended, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent "
        "FROM lessons l LEFT JOIN attendance a ON a.lesson_id=l.id "
        "WHERE l.date=? GROUP BY l.group_id",
        (today,),
    )
    stats = {int(r["group_id"]): r for r in stats_rows}
    text = f"✅ <b>Davomat</b> · {esc(fmt_date_long(today))}\n\nGuruhni tanlang:\n"
    rows: list[list[tuple[str, str]]] = []
    for group in items:
        stat = stats.get(int(group["id"]))
        suffix = ""
        if stat and int(stat.get("total") or 0):
            suffix = f" · {int(stat['total']) - int(stat['absent'] or 0)}/{int(stat['total'])}"
        else:
            suffix = " · belgilanmagan"
        text += f"\n• <b>{esc(group['name'])}</b>{suffix}"
        rows.append([(f"{group['name']}{suffix}"[:58], f"att:g:{group['id']}:{today}:1")])
    if not items:
        text += "\n\nSizga guruh biriktirilmagan."
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.callback_query(F.data.startswith("att:g:"))
async def attendance_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    group_id = safe_int(parts[2])
    date_value = parts[3] if len(parts) > 3 else today_str(settings.tz)
    page = safe_int(parts[4] if len(parts) > 4 else 1, 1, 1, 999)
    await show_attendance(callback, db, user, group_id, date_value, page)
    await callback.answer()


@router.callback_query(F.data.startswith("att:nav:"))
async def attendance_nav(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, date_value, delta_s = callback.data.split(":")
    new_date = add_days(date_value, safe_int(delta_s, 0, -30, 30) or -1)
    await show_attendance(callback, db, user, safe_int(group_id_s), new_date, 1)
    await callback.answer()


@router.callback_query(F.data.startswith("att:t:"))
async def attendance_toggle(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, lesson_id_s, student_id_s, page_s = callback.data.split(":")
    lesson_id = safe_int(lesson_id_s)
    student_id = safe_int(student_id_s)
    page = safe_int(page_s, 1, 1, 999)
    lesson = await attendance.get_lesson(db, lesson_id)
    if not lesson or not await permissions.can_manage_group(db, user, int(lesson["group_id"])):
        await ui.deny(callback)
        return
    entry = await db.fetchone("SELECT status FROM attendance WHERE lesson_id=? AND student_id=?", (lesson_id, student_id))
    current = entry["status"] if entry else "present"
    new_status = CYCLE.get(current, "present")
    await attendance.set_status(
        db,
        lesson_id=lesson_id,
        student_id=student_id,
        status=new_status,
        marked_by=int(user["id"]),
        check_in=await _local_time() if new_status in ("present", "late") else None,
    )
    await show_attendance(callback, db, user, int(lesson["group_id"]), lesson["date"], page)
    await callback.answer(f"{STATUS_ICON.get(new_status, '')} {status_label(new_status)}")


@router.callback_query(F.data.startswith("att:all:"))
async def attendance_all_present(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, date_value = callback.data.split(":")
    group_id = safe_int(group_id_s)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    lesson = await attendance.ensure_lesson(db, group_id, date_value, group.get("teacher_id"))
    roster = await students.list_students(db, group_id=group_id, status="active", limit=300)
    now = await _local_time()
    await attendance.save_entries(
        db,
        lesson_id=int(lesson["id"]),
        entries=[{"student_id": s["id"], "status": "present"} for s in roster],
        marked_by=int(user["id"]),
        default_check_in=now,
    )
    await show_attendance(callback, db, user, group_id, date_value, 1)
    await callback.answer("Hammasi keldi deb belgilandi")


@router.callback_query(F.data.startswith("att:save:"))
async def attendance_save(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, lesson_id_s, group_id_s, date_value = callback.data.split(":")
    lesson_id = safe_int(lesson_id_s)
    group_id = safe_int(group_id_s)
    lesson = await attendance.get_lesson(db, lesson_id)
    if not lesson or not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id) or {}
    roster = await students.list_students(db, group_id=group_id, status="active", limit=300)
    existing = await attendance.lesson_entries(db, lesson_id)
    now = await _local_time()
    entries = []
    for student in roster:
        entry = existing.get(int(student["id"]), {})
        entries.append({
            "student_id": student["id"],
            "status": entry.get("status", "present"),
            "check_in": entry.get("check_in"),
            "check_out": entry.get("check_out"),
            "minutes_late": entry.get("minutes_late", 0),
            "note": entry.get("note"),
        })
    counts = await attendance.save_entries(
        db, lesson_id=lesson_id, entries=entries, marked_by=int(user["id"]), default_check_in=now
    )
    await audit(db, user, "attendance_save", "lesson", lesson_id, counts)
    auto = await settings_service.get_bool(db, "auto_absence_notify", True)
    queued = {"queued": 0, "unlinked": 0}
    if auto and (counts["absent"] or counts["late"]):
        queued = await _queue_notifications(db, lesson_id)
        await audit(db, user, "attendance_notify", "lesson", lesson_id, {"queued": queued["queued"]})
    total = sum(counts.values())
    text = (
        f"✅ <b>Davomat saqlandi</b>\n\n"
        f"🗂 {esc(group.get('name') or '')}\n"
        f"📅 {esc(fmt_date_long(date_value))}\n"
        f"👥 Jami: <b>{total}</b>\n\n"
        f"✅ Keldi: <b>{counts['present']}</b>\n"
        f"⏰ Kechikdi: <b>{counts['late']}</b>\n"
        f"❌ Kelmadi: <b>{counts['absent']}</b>\n"
        f"📝 Sababli: <b>{counts['excused']}</b>\n"
    )
    if auto and (counts["absent"] or counts["late"]):
        text += (
            f"\n🔔 Ota-onalarga xabar navbatga qo'yildi: <b>{queued['queued']}</b>"
            + (f"\n⚠️ Telegram ulanmagan ota-onalar: <b>{queued['unlinked']}</b>" if queued["unlinked"] else "")
        )
    elif counts["absent"] or counts["late"]:
        text += "\n\n🔔 Xabarlar yuborilmadi. Quyidagi tugma orqali yuborishingiz mumkin."
    rows: list[list[tuple[str, str]]] = []
    if counts["absent"] or counts["late"]:
        rows.append([(f"🔔 Xabar yuborish ({counts['absent'] + counts['late']})", f"att:notify:{lesson_id}:{group_id}:{date_value}")])
    rows.append([("✏️ Davomatni tahrirlash", f"att:g:{group_id}:{date_value}:1")])
    rows.append([("🗂 Guruh kartasi", f"grp:v:{group_id}"), ("🏠 Bosh menyu", "home")])
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer("Saqlandi")


async def _queue_notifications(db: Database, lesson_id: int) -> dict[str, int]:
    lesson = await attendance.get_lesson(db, lesson_id)
    if not lesson:
        return {"queued": 0, "unlinked": 0}
    group = await groups.get_group(db, int(lesson["group_id"])) or {}
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    rows = await db.fetchall(
        "SELECT a.status, a.note, s.id AS student_id, s.full_name FROM attendance a "
        "JOIN students s ON s.id=a.student_id "
        "WHERE a.lesson_id=? AND a.status IN ('absent','late')",
        (lesson_id,),
    )
    total_queued = 0
    total_unlinked = 0
    for row in rows:
        text = messages.absence_message(
            student_name=row["full_name"],
            group_name=group.get("name") or lesson.get("group_name") or "—",
            date=lesson["date"],
            status=row["status"],
            teacher_name=group.get("teacher_name"),
            center_name=center,
            support=support,
            note=row.get("note"),
        )
        result = await notifications.queue_to_parents(
            db,
            student_id=int(row["student_id"]),
            kind="absent" if row["status"] == "absent" else "late",
            text=text,
            dedupe_base=f"att:{lesson_id}:{row['student_id']}:{row['status']}",
        )
        total_queued += result["queued"]
        total_unlinked += result["unlinked"]
    return {"queued": total_queued, "unlinked": total_unlinked}


@router.callback_query(F.data.startswith("att:notify:"))
async def attendance_notify_manual(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, lesson_id_s, group_id_s, date_value = callback.data.split(":")
    lesson_id = safe_int(lesson_id_s)
    group_id = safe_int(group_id_s)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    result = await _queue_notifications(db, lesson_id)
    await audit(db, user, "attendance_notify_manual", "lesson", lesson_id, {"queued": result["queued"]})
    await callback.answer(
        f"Navbatga qo'yildi: {result['queued']}" + (f", ulanmagan: {result['unlinked']}" if result["unlinked"] else ""),
        show_alert=True,
    )


@router.callback_query(F.data.startswith("att:time:"))
async def attendance_time_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, date_value, student_id_s, page_s = callback.data.split(":")
    group_id = safe_int(group_id_s)
    student_id = safe_int(student_id_s)
    page = safe_int(page_s, 1, 1, 999)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id)
    lesson = await attendance.ensure_lesson(db, group_id, date_value, group.get("teacher_id") if group else None)
    student = await students.get_student(db, student_id)
    entry = await db.fetchone(
        "SELECT * FROM attendance WHERE lesson_id=? AND student_id=?", (lesson["id"], student_id)
    ) or {}
    text = (
        f"🕒 <b>{esc(student['full_name'] if student else '')}</b>\n"
        f"📅 {esc(fmt_date_long(date_value))}\n\n"
        f"Status: {status_label(entry.get('status', 'present'))}\n"
        f"Keldi: <b>{esc(entry.get('check_in') or '—')}</b>\n"
        f"Ketdi: <b>{esc(entry.get('check_out') or '—')}</b>"
    )
    rows = [
        [("🟢 Keldi (hozir)", f"att:in:{group_id}:{date_value}:{student_id}:{page}"),
         ("🔴 Ketdi (hozir)", f"att:out:{group_id}:{date_value}:{student_id}:{page}")],
        [("📝 Izoh", f"att:note:{group_id}:{date_value}:{student_id}:{page}"),
         ("🧹 Tozalash", f"att:clr:{group_id}:{date_value}:{student_id}:{page}")],
        [("⬅️ Davomat", f"att:g:{group_id}:{date_value}:{page}")],
    ]
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


async def _time_action(callback: CallbackQuery, db: Database, user: dict, action: str) -> None:
    _, _, group_id_s, date_value, student_id_s, page_s = callback.data.split(":")
    group_id = safe_int(group_id_s)
    student_id = safe_int(student_id_s)
    page = safe_int(page_s, 1, 1, 999)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id)
    lesson = await attendance.ensure_lesson(db, group_id, date_value, group.get("teacher_id") if group else None)
    if action == "clr":
        await attendance.clear_times(db, lesson_id=int(lesson["id"]), student_id=student_id)
        msg = "Tozalandi"
    else:
        now = await _local_time()
        await attendance.set_times(
            db,
            lesson_id=int(lesson["id"]),
            student_id=student_id,
            check_in=now if action == "in" else None,
            check_out=now if action == "out" else None,
            marked_by=int(user["id"]),
        )
        msg = f"{'Keldi' if action == 'in' else 'Ketdi'}: {now}"
    await show_attendance(callback, db, user, group_id, date_value, page)
    await callback.answer(msg)


@router.callback_query(F.data.startswith("att:in:"))
async def attendance_in(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _time_action(callback, db, user, "in")


@router.callback_query(F.data.startswith("att:out:"))
async def attendance_out(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _time_action(callback, db, user, "out")


@router.callback_query(F.data.startswith("att:clr:"))
async def attendance_clear(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _time_action(callback, db, user, "clr")


@router.callback_query(F.data.startswith("att:note:"))
async def attendance_note_start(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, date_value, student_id_s, page_s = callback.data.split(":")
    group_id = safe_int(group_id_s)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    await state.clear()
    await state.set_state(AttendanceNote.value)
    await state.update_data(
        group_id=group_id, date_value=date_value, student_id=safe_int(student_id_s),
        page=safe_int(page_s, 1, 1, 999),
    )
    await ui.send(callback, "📝 Qisqa izoh kiriting (sabab, kechikish va h.k.).", kb.ikb([
        [("⬅️ Orqaga", f"att:g:{group_id}:{date_value}:1")],
    ]))
    await callback.answer()


@router.message(AttendanceNote.value)
async def attendance_note_save(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    data = await state.get_data()
    group_id = int(data.get("group_id") or 0)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(message)
        return
    group = await groups.get_group(db, group_id)
    lesson = await attendance.ensure_lesson(db, group_id, data.get("date_value"), group.get("teacher_id") if group else None)
    note = clean_text(message.text or "", 200)
    if not note:
        await message.answer("❌ Izoh bo'sh.")
        return
    await attendance.set_note(db, lesson_id=int(lesson["id"]), student_id=int(data.get("student_id") or 0), note=note)
    await state.clear()
    await message.answer("✅ Izoh saqlandi.")
    await show_attendance(message, db, user, group_id, data.get("date_value"), int(data.get("page") or 1))


@router.callback_query(F.data.startswith("att:topic:"))
async def attendance_topic_start(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, date_value = callback.data.split(":")
    group_id = safe_int(group_id_s)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    await state.clear()
    await state.set_state(LessonTopic.value)
    await state.update_data(group_id=group_id, date_value=date_value)
    await ui.send(callback, "📖 Dars mavzusini kiriting:", kb.ikb([
        [("⬅️ Orqaga", f"att:g:{group_id}:{date_value}:1")],
    ]))
    await callback.answer()


@router.message(LessonTopic.value)
async def attendance_topic_save(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    data = await state.get_data()
    group_id = int(data.get("group_id") or 0)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(message)
        return
    group = await groups.get_group(db, group_id)
    lesson = await attendance.ensure_lesson(db, group_id, data.get("date_value"), group.get("teacher_id") if group else None)
    topic = clean_text(message.text or "", 120) or None
    await attendance.set_topic(db, int(lesson["id"]), topic)
    await state.clear()
    await message.answer("✅ Mavzu saqlandi.")
    await show_attendance(message, db, user, group_id, data.get("date_value"), 1)


@router.callback_query(F.data.startswith("att:hist:"))
async def attendance_history(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id)
    lessons = await attendance.recent_lessons(db, group_id, 12)
    text = f"🕘 <b>{esc(group['name'] if group else '')}</b> — oxirgi darslar\n\n"
    rows: list[list[tuple[str, str]]] = []
    for lesson in lessons:
        text += (
            f"📅 {esc(fmt_date(lesson['date']))} — ✅{lesson['present_count']} "
            f"⏰{lesson['late_count']} ❌{lesson['absent_count']} 📝{lesson['excused_count']}\n"
        )
        rows.append([(f"📅 {fmt_date(lesson['date'])}", f"att:g:{group_id}:{lesson['date']}:1")])
    if not lessons:
        text += "Hozircha dars yo'q."
    rows.append(kb.nav_row(f"grp:v:{group_id}"))
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()
