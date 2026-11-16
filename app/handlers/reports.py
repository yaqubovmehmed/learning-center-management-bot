"""Hisobotlar: davomat, testlar, xavf ostidagilar, yuklama, CSV, digest."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import exports, groups, messages, notifications, permissions, reports, settings as settings_service, teachers, tests
from app.utils import esc, fmt_date, paginate, safe_int, today_str
from config import settings

router = Router(name="reports")

PERIODS = {"7": "7 kun", "30": "30 kun", "90": "90 kun", "month": "Shu oy"}


async def _scope_teacher_id(db: Database, user: dict) -> int | None:
    if permissions.is_admin(user):
        return None
    teacher = await permissions.teacher_profile(db, user)
    return teacher["id"] if teacher else -1


@router.message(F.text.in_({"📊 Hisobotlar", "📊 Hisobot"}))
async def reports_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    await _menu(message, db, user)


@router.callback_query(F.data == "rep:menu")
async def reports_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _menu(callback, db, user)
    await callback.answer()


async def _menu(event: Message | CallbackQuery, db: Database, user: dict) -> None:
    today = today_str(settings.tz)
    overall = await reports.overall_attendance(db, today[:8] + "01", today)
    threshold = float(await settings_service.get_int(db, "attendance_threshold", 75))
    risk = await reports.risk_students(db, settings.tz, threshold)
    if not permissions.is_admin(user):
        teacher = await permissions.teacher_profile(db, user)
        if teacher:
            risk = [r for r in risk if int(r.get("teacher_id") or 0) == int(teacher["id"])]
    rate = overall.get("rate")
    rate_text = f"{rate:.0f}%" if rate is not None else "—"
    text = (
        f"📊 <b>Hisobotlar</b>\n"
        f"📅 {esc(today)}\n\n"
        f"✅ Shu oy davomati: <b>{rate_text}</b>"
    )
    text += f"\n⚠️ E'tibor talab qiladi: <b>{len(risk)}</b> o'quvchi"
    rows: list[list[tuple[str, str]]] = [
        [("✅ Davomat hisoboti", "rep:att"), ("📝 Test tahlili", "rep:tests:1")],
        [("⚠️ Xavf ostidagilar", "rep:risk:1"), ("📥 CSV eksport", "rep:csv")],
    ]
    if permissions.is_admin(user):
        rows.append([("👨‍🏫 O'qituvchilar yuklamasi", "rep:load")])
        rows.append([("📅 Haftalik hisobotlarni yuborish", "rep:digest")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


# ---------- Davomat hisoboti ----------

@router.callback_query(F.data == "rep:att")
async def attendance_report_groups(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    teacher_id = await _scope_teacher_id(db, user)
    items = await groups.list_groups(db, teacher_id=teacher_id)
    rows: list[list[tuple[str, str]]] = []
    if permissions.is_admin(user):
        rows.append([("📊 Barcha guruhlar", "rep:attg:0")])
    for group in items:
        rows.append([(f"🗂 {group['name']}"[:55], f"rep:attg:{group['id']}")])
    rows.append(kb.nav_row("rep:menu"))
    await ui.send(callback, "✅ <b>Davomat hisoboti</b>\n\nGuruhni tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:attg:"))
async def attendance_report_periods(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if group_id and not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    rows = [[(label, f"rep:attp:{group_id}:{period}:1")] for period, label in PERIODS.items()]
    rows.append(kb.nav_row("rep:att"))
    await ui.send(callback, "📅 Davrni tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:attp:"))
async def attendance_report(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    group_id = safe_int(parts[2])
    period = parts[3] if len(parts) > 3 else "30"
    page = safe_int(parts[4] if len(parts) > 4 else 1, 1, 1, 999)
    if group_id and not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    start, end, label = reports.period_range(period, settings.tz)
    threshold = float(await settings_service.get_int(db, "attendance_threshold", 75))
    if group_id:
        data = await reports.group_report(db, group_id, start, end, threshold)
        if not data:
            await callback.answer("Topilmadi", show_alert=True)
            return
        group = data["group"]
        rows_data = data["rows"]
        chunk, page, pages, total = paginate(rows_data, page, 12)
        overall = await reports.overall_attendance_for_group(db, group_id, start, end)
        text = (
            f"✅ <b>{esc(group['name'])}</b> — davomat\n"
            f"📅 {esc(fmt_date(start))} — {esc(fmt_date(end))} ({esc(label)})\n\n"
            f"👥 O'quvchilar: <b>{total}</b>\n"
            f"📊 Umumiy: <b>{(overall.get('rate') or 0):.0f}%</b> · "
            f"✅{overall['present']} ⏰{overall['late']} ❌{overall['absent']} 📝{overall['excused']}\n\n"
        )
        for row in chunk:
            rate = row["rate"]
            text += (
                f"• {esc(row['full_name'])} — "
                + (f"<b>{rate:.0f}%</b> {('▰' * max(1, round(rate / 10)))}" if rate is not None else "—")
                + f" (❌{row['absent']})\n"
            )
        rows: list[list[tuple[str, str]]] = []
        if pages > 1:
            rows.append(kb.pager(f"rep:attp:{group_id}:{period}", page, pages))
        rows.append([("📥 CSV", f"rep:attcsv:{group_id}:{period}")])
        rows.append(kb.nav_row("rep:att"))
    else:
        today = today_str(settings.tz)
        overall = await reports.overall_attendance(db, start, end)
        teacher_id = await _scope_teacher_id(db, user)
        all_groups = await groups.list_groups(db, teacher_id=teacher_id)
        text = (
            f"✅ <b>Barcha guruhlar</b> — davomat\n"
            f"📅 {esc(fmt_date(start))} — {esc(fmt_date(end))} ({esc(label)})\n\n"
            f"📊 Umumiy: <b>{(overall.get('rate') or 0):.0f}%</b>\n"
            f"✅{overall['present']} · ⏰{overall['late']} · ❌{overall['absent']} · 📝{overall['excused']}\n"
        )
        for group in all_groups:
            data_g = await reports.group_report(db, int(group["id"]), start, end, threshold)
            rates = [r["rate"] for r in data_g.get("rows", []) if r["rate"] is not None]
            avg = sum(rates) / len(rates) if rates else None
            text += f"\n🗂 {esc(group['name'])} — " + (f"<b>{avg:.0f}%</b>" if avg is not None else "—")
        rows = [kb.nav_row("rep:att")]
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:attcsv:"))
async def attendance_csv_export(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, group_id_s, period = callback.data.split(":")
    group_id = safe_int(group_id_s)
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    start, end, _label = reports.period_range(period, settings.tz)
    data, filename = await exports.attendance_csv(db, group_id, start, end)
    if callback.message:
        await callback.message.answer_document(BufferedInputFile(data, filename=filename), caption="📥 Davomat (CSV)")
    await audit(db, user, "export_attendance", "group", group_id)
    await callback.answer("Yuborildi")


# ---------- Test tahlili ----------

@router.callback_query(F.data.startswith("rep:tests:"))
async def test_report_list(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    teacher_id = await _scope_teacher_id(db, user)
    items = await tests.list_tests(db, teacher_id=teacher_id, limit=100)
    chunk, page, pages, total = paginate(items, page, 10)
    text = f"📝 <b>Test tahlili</b>\n\nJami: <b>{total}</b>\n"
    rows: list[list[tuple[str, str]]] = []
    for test in chunk:
        text += f"\n• {esc(test['title'])} — {esc(test['group_name'])} · {esc(fmt_date(test['date']))}"
        rows.append([(f"📈 {test['title']} · {fmt_date(test['date'])}"[:55], f"tst:stats:{test['id']}")])
    if not items:
        text += "\nHozircha test yo'q."
    if pages > 1:
        rows.append(kb.pager("rep:tests", page, pages))
    rows.append(kb.nav_row("rep:menu"))
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


# ---------- Xavf ostidagilar ----------

@router.callback_query(F.data.startswith("rep:risk:"))
async def risk_list(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    threshold = float(await settings_service.get_int(db, "attendance_threshold", 75))
    items = await reports.risk_students(db, settings.tz, threshold)
    if not permissions.is_admin(user):
        teacher = await permissions.teacher_profile(db, user)
        if teacher:
            items = [i for i in items if int(i.get("teacher_id") or 0) == int(teacher["id"])]
    chunk, page, pages, total = paginate(items, page, 8)
    text = (
        f"⚠️ <b>E'tibor talab qiladigan o'quvchilar</b>\n\n"
        f"Jami: <b>{total}</b>\n"
        "Mezon: davomat me'yordan past yoki oxirgi test 50% dan past.\n"
    )
    rows: list[list[tuple[str, str]]] = []
    for item in chunk:
        reasons = ", ".join(item["reasons"])
        text += f"\n• <b>{esc(item['name'])}</b> — {esc(item['group'] or '—')}\n  {esc(reasons)}\n"
        rows.append([(f"👤 {item['name']}", f"stu:v:{item['id']}"), ("🔔", f"rep:riskmsg:{item['id']}")])
    if not items:
        text += "\nHammasi yaxshi — xavf ostida hech kim yo'q."
    if pages > 1:
        rows.append(kb.pager("rep:risk", page, pages))
    rows.append(kb.nav_row("rep:menu"))
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:riskmsg:"))
async def risk_notify(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    student_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    student = await db.fetchone(
        "SELECT s.*, g.name AS group_name, t.name AS teacher_name FROM students s "
        "LEFT JOIN groups g ON g.id=s.group_id LEFT JOIN teachers t ON t.id=g.teacher_id WHERE s.id=?",
        (student_id,),
    )
    if not student:
        await callback.answer("Topilmadi", show_alert=True)
        return
    today = today_str(settings.tz)
    start = today[:8] + "01"
    from app.services import attendance

    att = await attendance.summary(db, student_id, start, today)
    latest = await tests.latest_for_student(db, student_id, published_only=True)
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    text = (
        f"⚠️ <b>Diqqat talab qiladi</b>\n\n"
        f"👤 <b>{esc(student['full_name'])}</b>\n"
        f"🗂 {esc(student.get('group_name') or '—')}\n\n"
    )
    if att.get("rate") is not None:
        text += f"✅ Davomat: <b>{att['rate']:.0f}%</b> · kelmagan {att['absent']} kun\n"
    if latest:
        percent = (float(latest["score"]) / float(latest["max_score"]) * 100) if latest["max_score"] else 0
        text += f"📝 Oxirgi test: <b>{percent:.0f}%</b>\n"
    text += (
        "\nIltimos, farzandingizning darslarga qatnashishini nazorat qiling va "
        "o'qituvchi bilan bog'laning."
    )
    if support:
        handle = support if support.startswith("@") else "@" + support
        text += f"\n☎️ {esc(handle)}"
    result = await notifications.queue_to_parents(
        db,
        student_id=student_id,
        kind="alert",
        text=text,
        dedupe_base=f"risk:{student_id}:{today}",
    )
    await audit(db, user, "risk_notify", "student", student_id, {"queued": result["queued"]})
    await callback.answer(
        f"Yuborildi: {result['queued']}" + (f", ulanmagan: {result['unlinked']}" if result["unlinked"] else ""),
        show_alert=True,
    )


# ---------- Yuklama ----------

@router.callback_query(F.data == "rep:load")
async def teacher_load(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    items = await teachers.list_teachers(db)
    text = "👨‍🏫 <b>O'qituvchilar yuklamasi</b>\n"
    rows: list[list[tuple[str, str]]] = []
    for teacher in items:
        text += (
            f"\n• <b>{esc(teacher['name'])}</b> — {teacher['groups_count']} guruh, "
            f"{teacher['students_count']} o'quvchi"
        )
        rows.append([(f"👨‍🏫 {teacher['name']}"[:55], f"tch:v:{teacher['id']}")])
    if not items:
        text += "\nO'qituvchi yo'q."
    rows.append(kb.nav_row("rep:menu"))
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


# ---------- CSV ----------

@router.callback_query(F.data == "rep:csv")
async def csv_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await ui.send(
        callback,
        "📥 <b>CSV eksport</b>\n\nQaysi ma'lumotni yuklaysiz?",
        kb.ikb([
            [("👥 O'quvchilar ro'yxati", "rep:csv:students")],
            [("✅ Davomat", "rep:csv:att")],
            kb.nav_row("rep:menu"),
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "rep:csv:students")
async def students_csv_export(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    teacher_id = await _scope_teacher_id(db, user)
    data, filename = await exports.students_csv(db, teacher_id)
    if callback.message:
        await callback.message.answer_document(BufferedInputFile(data, filename=filename), caption="📥 O'quvchilar (CSV)")
    await audit(db, user, "export_students")
    await callback.answer("Yuborildi")


@router.callback_query(F.data == "rep:csv:att")
async def attendance_csv_groups(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    teacher_id = await _scope_teacher_id(db, user)
    items = await groups.list_groups(db, teacher_id=teacher_id)
    rows = [[(f"🗂 {g['name']}"[:55], f"rep:csvg:{g['id']}")] for g in items]
    rows.append(kb.nav_row("rep:csv"))
    await ui.send(callback, "✅ Qaysi guruh davomati?", kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:csvg:"))
async def attendance_csv_periods(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    rows = [[(label, f"rep:attcsv:{group_id}:{period}")] for period, label in PERIODS.items()]
    rows.append(kb.nav_row("rep:csv"))
    await ui.send(callback, "📅 Davrni tanlang:", kb.ikb(rows))
    await callback.answer()


# ---------- Digest ----------

@router.callback_query(F.data == "rep:digest")
async def digest_prompt(callback: CallbackQuery, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await ui.send(
        callback,
        "📅 <b>Haftalik hisobot</b>\n\n"
        "Barcha ulangan ota-onalarga shu haftalik davomat va oxirgi test natijalari yuborilsinmi?\n\n"
        "Takroriy yuborishdan himoya qilingan — bir haftada bir marta.",
        kb.confirm_kb("rep:digestyes", "rep:menu", "📅 Ha, yuborish"),
    )
    await callback.answer()


@router.callback_query(F.data == "rep:digestyes")
async def digest_send(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    count = await notifications.queue_weekly_digests(db, settings.tz)
    await audit(db, user, "digest_manual", details={"queued": count})
    await callback.answer(f"Navbatga qo'yildi: {count}", show_alert=True)
