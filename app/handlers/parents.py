"""Ota-ona paneli: farzandlar, davomat, natijalar, sozlamalar."""
from __future__ import annotations

from datetime import date
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.filters import RoleFilter
from app.security import audit
from app.services import attendance, messages, notifications, permissions, reports, settings as settings_service, students, tests
from app.states import ParentReason
from app.utils import esc, fmt_date, format_days, score_percent, status_label, today_str
from config import settings

router = Router(name="parents")

PREF_LABELS = {
    "notif_absent": ("❌ Kelmaganida xabar", "Darsga kelmasa darhol xabar"),
    "notif_late": ("⏰ Kechikkanida xabar", "Kechiksa xabar"),
    "notif_results": ("📊 Test natijalari", "Har testdan keyin natija"),
    "notif_weekly": ("📅 Haftalik hisobot", "Har dushanba umumiy hisobot"),
}


async def _parent(db: Database, user: dict) -> dict[str, Any] | None:
    return await students.get_parent_by_user_id(db, int(user["id"]))


async def _children(db: Database, user: dict) -> list[dict[str, Any]]:
    return await students.children_of_user(db, int(user["id"]))


async def _pick_child(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    state: FSMContext,
    *,
    target: str,
    title: str,
) -> None:
    children = await _children(db, user)
    if not children:
        await ui.send(event, "Hozircha farzandlaringiz ulanmagan. Administrator bilan bog'laning.")
        return
    if len(children) == 1:
        child = children[0]
        if target == "att":
            await show_child_attendance(event, db, user, int(child["id"]))
        elif target == "res":
            await show_child_results(event, db, user, int(child["id"]))
        elif target == "reason":
            await _begin_reason(event, db, user, state, int(child["id"]), "absence")
        else:
            await show_child(event, db, user, int(child["id"]))
        return
    rows = [[(f"👶 {c['full_name']}"[:55], f"par:{target}:{c['id']}")] for c in children]
    rows.append(kb.nav_row("home"))
    await ui.send(event, title, kb.ikb(rows))


@router.message(F.text == "👶 Farzandlarim")
async def children_menu(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "parent"):
        return
    children = await _children(db, user)
    text = "👶 <b>Farzandlaringiz</b>\n\n"
    rows: list[list[tuple[str, str]]] = []
    if not children:
        text += "Hozircha ulanmagan."
    for child in children:
        text += f"• <b>{esc(child['full_name'])}</b> — {esc(child.get('group_name') or 'guruhsiz')}\n"
        rows.append([(f"👶 {child['full_name']}"[:55], f"par:child:{child['id']}")])
    rows.append([("✉️ Sabab yuborish", "par:absence"), ("📊 Natijalar", "par:results")])
    rows.append(kb.nav_row("home"))
    await message.answer(text, reply_markup=kb.ikb(rows))


@router.callback_query(F.data.startswith("par:child:"))
async def child_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    student_id = int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    await show_child(callback, db, user, student_id)
    await callback.answer()


async def show_child(event: Message | CallbackQuery, db: Database, user: dict, student_id: int) -> None:
    child = await students.get_student(db, student_id)
    if not child:
        await ui.toast(event, "Topilmadi", True)
        return
    today = date.fromisoformat(today_str(settings.tz))
    start = today.replace(day=1).isoformat()
    att = await attendance.summary(db, student_id, start, today.isoformat())
    latest = await tests.latest_for_student(db, student_id, published_only=True)
    text = (
        f"👶 <b>{esc(child['full_name'])}</b>\n"
        f"🗂 {esc(child.get('group_name') or 'guruhsiz')}\n"
        f"👨‍🏫 {esc(child.get('teacher_name') or '—')}\n"
        f"📅 Jadval: {esc(format_days(child.get('group_days')))} · {esc(child.get('group_time') or '—')}\n\n"
        f"✅ <b>Shu oy davomati</b>\n"
    )
    if att.get("rate") is None:
        text += "Hozircha dars belgilanmagan.\n"
    else:
        text += (
            f"Kelgan: <b>{att['present'] + att['late']}</b> kun · "
            f"Kelmagan: <b>{att['absent']}</b> · Kechikkan: <b>{att['late']}</b>\n"
            f"Ko'rsatkich: <b>{att['rate']:.0f}%</b>\n"
        )
    if latest:
        percent = score_percent(latest["score"], float(latest["max_score"])) or 0
        text += f"\n📝 Oxirgi test: <b>{esc(latest['title'])}</b> — {percent:.0f}% ({esc(fmt_date(latest['date']))})"
    else:
        text += "\n📝 Hozircha test natijasi yo'q."
    rows = [
        [("✅ Davomat tarixi", f"par:att:{student_id}"), ("📊 Test natijalari", f"par:res:{student_id}")],
        [("✉️ Sabab yuborish", f"par:reason:{student_id}"), ("💬 O'qituvchiga xabar", f"par:msg:{student_id}")],
        [("👶 Farzandlarim", "par:children")],
        [("🏠 Bosh menyu", "home")],
    ]
    await ui.send(event, text, kb.ikb(rows))


@router.callback_query(F.data == "par:children")
async def children_callback(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    children = await _children(db, user)
    rows = [[(f"👶 {c['full_name']}"[:55], f"par:child:{c['id']}")] for c in children]
    rows.append(kb.nav_row("home"))
    await ui.send(callback, "👶 <b>Farzandlaringiz</b>", kb.ikb(rows))
    await callback.answer()


# ---------- Davomat ----------

@router.message(RoleFilter("parent"), F.text == "✅ Davomat")
async def attendance_menu_parent(message: Message, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(message, user, "parent"):
        return
    await _pick_child(message, db, user, state, target="att", title="✅ Qaysi farzandning davomatini ko'rasiz?")


@router.callback_query(F.data == "par:attendance")
async def attendance_menu_parent_cb(callback: CallbackQuery, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    await _pick_child(callback, db, user, state, target="att", title="✅ Qaysi farzandning davomatini ko'rasiz?")
    await callback.answer()


@router.callback_query(F.data.startswith("par:att:"))
async def child_attendance(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    student_id = int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    await show_child_attendance(callback, db, user, student_id)
    await callback.answer()


async def show_child_attendance(event: Message | CallbackQuery, db: Database, user: dict, student_id: int) -> None:
    child = await students.get_student(db, student_id)
    today = date.fromisoformat(today_str(settings.tz))
    start = today.replace(day=1).isoformat()
    summary = await attendance.summary(db, student_id, start, today.isoformat())
    rows = await attendance.student_history(db, student_id, 20)
    text = f"✅ <b>{esc(child['full_name'] if child else '')}</b> — davomat\n\n"
    if summary.get("rate") is not None:
        text += (
            f"Shu oy: <b>{summary['rate']:.0f}%</b> · "
            f"kelgan {summary['present'] + summary['late']} · kelmagan {summary['absent']}\n\n"
        )
    if not rows:
        text += "Hozircha yozuv yo'q."
    for row in rows:
        icon = {"present": "✅", "absent": "❌", "late": "⏰", "excused": "📝"}.get(row["status"], "•")
        text += f"{icon} {esc(fmt_date(row['date']))} — {status_label(row['status'])}"
        if row.get("check_in"):
            text += f" · 🕒 {esc(row['check_in'])}"
        text += "\n"
    await ui.send(event, text, kb.ikb([
        [("✉️ Sabab yuborish", f"par:reason:{student_id}")],
        kb.nav_row(f"par:child:{student_id}"),
    ]))


# ---------- Natijalar ----------

@router.message(F.text == "📊 Natijalar")
async def results_menu_parent(message: Message, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(message, user, "parent"):
        return
    await _pick_child(message, db, user, state, target="res", title="📊 Qaysi farzandning natijalarini ko'rasiz?")


@router.callback_query(F.data == "par:results")
async def results_menu_parent_cb(callback: CallbackQuery, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    await _pick_child(callback, db, user, state, target="res", title="📊 Qaysi farzandning natijalarini ko'rasiz?")
    await callback.answer()


@router.callback_query(F.data.startswith("par:res:"))
async def child_results(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    student_id = int(callback.data.split(":")[2])
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(callback)
        return
    await show_child_results(callback, db, user, student_id)
    await callback.answer()


async def show_child_results(event: Message | CallbackQuery, db: Database, user: dict, student_id: int) -> None:
    child = await students.get_student(db, student_id)
    rows = await tests.results_for_student(db, student_id, 20, published_only=True)
    text = f"📊 <b>{esc(child['full_name'] if child else '')}</b> — natijalar\n\n"
    if not rows:
        text += "Hozircha test natijasi yo'q."
    previous_percent: float | None = None
    for row in reversed(rows):
        if row["is_absent"]:
            text += f"❌ {esc(fmt_date(row['date']))} · {esc(row['title'])} — qatnashmadi\n"
            continue
        percent = score_percent(row["score"], float(row["max_score"])) or 0
        line = f"📝 {esc(fmt_date(row['date']))} · {esc(row['title'])}: <b>{percent:.0f}%</b>"
        if previous_percent is not None:
            delta = percent - previous_percent
            if abs(delta) >= 1:
                line += f" ({'📈 +' if delta > 0 else '📉 '}{delta:.0f}%)"
        if row.get("band") is not None and float(row["max_score"]) == 40:
            line += f" · band {row['band']:.1f}"
        text += line + "\n"
        previous_percent = percent
    text += (
        "\n💡 <b>Qanday o'qish kerak?</b>\n"
        "Foiz qanchalik yuqori bo'lsa, natija shunchalik yaxshi. "
        "O'sish (📈) — oldingi testdan yaxshilanganini bildiradi."
    )
    await ui.send(event, text, kb.ikb([
        [("✉️ O'qituvchiga xabar", f"par:msg:{student_id}")],
        kb.nav_row(f"par:child:{student_id}"),
    ]))


# ---------- Sabab / xabar ----------

@router.message(F.text == "✉️ Sabab yuborish")
async def absence_menu(message: Message, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(message, user, "parent"):
        return
    await _pick_child(message, db, user, state, target="reason", title="✉️ Qaysi farzand uchun sabab yuborasiz?")


@router.callback_query(F.data == "par:absence")
async def absence_menu_cb(callback: CallbackQuery, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    await _pick_child(callback, db, user, state, target="reason", title="✉️ Qaysi farzand uchun sabab yuborasiz?")
    await callback.answer()


@router.callback_query(F.data.startswith("par:reason:"))
async def start_reason(callback: CallbackQuery, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    student_id = int(callback.data.split(":")[2])
    await _begin_reason(callback, db, user, state, student_id, "absence")
    await callback.answer()


@router.callback_query(F.data.startswith("par:msg:"))
async def start_message(callback: CallbackQuery, db: Database, user: dict | None, state: FSMContext) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    student_id = int(callback.data.split(":")[2])
    await _begin_reason(callback, db, user, state, student_id, "message")
    await callback.answer()


async def _begin_reason(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    state: FSMContext,
    student_id: int,
    mode: str,
) -> None:
    if not await permissions.can_access_student(db, user, student_id):
        await ui.deny(event)
        return
    child = await students.get_student(db, student_id)
    if not child:
        await ui.toast(event, "Topilmadi", True)
        return
    await state.clear()
    await state.set_state(ParentReason.reason)
    await state.update_data(student_id=student_id, mode=mode)
    if mode == "absence":
        title = f"✉️ <b>{esc(child['full_name'])}</b> — kelmaslik sababi"
        prompt = (
            "Sababni qisqa yozing (10-400 belgi).\n"
            "Masalan: <i>Kasal bo'lgani uchun bugun darsga kela olmaydi.</i>\n\n"
            "Xabar o'qituvchiga yuboriladi va davomatda qayd etiladi."
        )
    else:
        title = f"💬 <b>{esc(child['full_name'])}</b> — o'qituvchiga xabar"
        prompt = "Xabaringizni yozing (10-400 belgi). O'qituvchi Telegram orqali oladi."
    await ui.send(event, f"{title}\n\n{prompt}", kb.ikb([kb.nav_row(f"par:child:{student_id}")]))


@router.message(ParentReason.reason)
async def reason_save(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "parent"):
        return
    data = await state.get_data()
    student_id = int(data.get("student_id") or 0)
    mode = data.get("mode") or "absence"
    if not await permissions.can_access_student(db, user, student_id):
        await state.clear()
        await ui.deny(message)
        return
    reason = " ".join((message.text or "").split())[:400]
    if len(reason) < 10:
        await message.answer("❌ Xabar juda qisqa. Kamida 10 belgi yozing.")
        return
    child = await students.get_student(db, student_id)
    parent = await _parent(db, user)
    if not child or not parent:
        await state.clear()
        await message.answer("Ma'lumot topilmadi.")
        return
    today = today_str(settings.tz)
    if mode == "absence":
        report_id = await attendance.add_absence_report(
            db, student_id=student_id, parent_id=int(parent["id"]), date=today, reason=reason
        )
        await audit(db, user, "parent_absence_report", "student", student_id, {"report_id": report_id})
    else:
        await audit(db, user, "parent_message", "student", student_id)
    teacher = await db.fetchone(
        "SELECT t.name, u.tg_id FROM students s JOIN groups g ON g.id=s.group_id "
        "LEFT JOIN teachers t ON t.id=g.teacher_id LEFT JOIN users u ON u.id=t.user_id WHERE s.id=?",
        (student_id,),
    )
    text = messages.absence_reason_to_teacher(
        student_name=child["full_name"],
        parent_name=parent["full_name"],
        parent_phone=parent.get("phone"),
        date=today,
        reason=reason,
        group_name=child.get("group_name"),
    )
    if mode == "message":
        text = (
            f"💬 <b>Ota-onadan xabar</b>\n\n"
            f"👤 {esc(child['full_name'])} · {esc(child.get('group_name') or '—')}\n"
            f"🙋 {esc(parent['full_name'])}\n\n{esc(reason)}"
        )
    delivered = 0
    dedupe = f"pnote:{student_id}:{report_id}" if mode == "absence" else None
    if teacher and teacher.get("tg_id"):
        if await notifications.queue_direct(
            db,
            kind="parent_note",
            tg_id=int(teacher["tg_id"]),
            text=text,
            dedupe_key=dedupe,
            student_id=student_id,
        ):
            delivered += 1
    else:
        admins = await db.fetchall(
            "SELECT tg_id FROM users WHERE role IN ('superadmin','admin') AND is_active=1"
        )
        for admin in admins:
            if await notifications.queue_direct(
                db,
                kind="parent_note",
                tg_id=int(admin["tg_id"]),
                text=text,
                dedupe_key=None if dedupe is None else f"{dedupe}:{admin['tg_id']}",
                student_id=student_id,
            ):
                delivered += 1
    await state.clear()
    await message.answer(
        ("✅ Sabab qabul qilindi va o'qituvchiga yuborildi." if mode == "absence" else "✅ Xabar yuborildi.")
        if delivered else "✅ Xabar saqlandi. O'qituvchi hali Telegramga ulanmagan, administrator ko'radi.",
        reply_markup=kb.ikb([[("👶 Farzand kartasi", f"par:child:{student_id}")], kb.nav_row("home")]),
    )


# ---------- Sozlamalar ----------

@router.message(F.text == "🔔 Sozlamalar")
async def parent_settings(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "parent"):
        return
    await _settings_view(message, db, user)


@router.callback_query(F.data == "par:settings")
async def parent_settings_cb(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    await _settings_view(callback, db, user)
    await callback.answer()


async def _settings_view(event: Message | CallbackQuery, db: Database, user: dict) -> None:
    parent = await _parent(db, user)
    if not parent:
        await ui.send(event, "Ota-ona profili topilmadi.")
        return
    text = "🔔 <b>Xabar sozlamalari</b>\n\nQaysi xabarlarni olishni o'zingiz tanlang:\n"
    rows: list[list[tuple[str, str]]] = []
    for key, (label, _desc) in PREF_LABELS.items():
        enabled = bool(int(parent.get(key) or 0))
        text += f"\n{'✅' if enabled else '⬜️'} {label}"
        rows.append([(f"{'✅' if enabled else '⬜️'} {label}", f"par:pref:{key}")])
    text += "\n\nO'zgarish darhol saqlanadi."
    rows.append([("📅 Haftalik hisobotni ko'rish", "par:digest")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.callback_query(F.data.startswith("par:pref:"))
async def parent_pref_toggle(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    field = callback.data.split(":")[2]
    if field not in PREF_LABELS:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    parent = await _parent(db, user)
    if not parent:
        await callback.answer("Profil yo'q", show_alert=True)
        return
    new_value = 0 if int(parent.get(field) or 0) else 1
    await db.execute(f"UPDATE parents SET {field}=? WHERE id=?", (new_value, parent["id"]))
    await audit(db, user, "parent_pref", "parent", parent["id"], {field: new_value})
    await _settings_view(callback, db, user)
    await callback.answer("Yoqildi" if new_value else "O'chirildi")


@router.callback_query(F.data == "par:digest")
async def parent_digest(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    parent = await _parent(db, user)
    if not parent:
        await callback.answer("Profil yo'q", show_alert=True)
        return
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    data = await reports.parent_digest_data(db, parent, settings.tz)
    text = messages.digest_message(
        parent_name=parent["full_name"],
        children=data,
        center_name=center,
        support=support,
    )
    await ui.send(callback, text, kb.ikb([kb.nav_row("par:settings")]))
    await callback.answer()


# ---------- Bog'lanish ----------

@router.message(F.text == "☎️ Bog'lanish")
async def contact_parent(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "parent"):
        return
    await _contact(message, db, user)


@router.callback_query(F.data == "par:contact")
async def contact_parent_cb(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "parent"):
        return
    await _contact(callback, db, user)
    await callback.answer()


async def _contact(event: Message | CallbackQuery, db: Database, user: dict) -> None:
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    text = f"☎️ <b>{esc(center)}</b>\n\n"
    if support:
        handle = support if support.startswith("@") else "@" + support
        text += f"Administrator: {esc(handle)}\n"
    else:
        text += "Administrator kontaktlari sozlanmagan. Markazga murojaat qiling.\n"
    children = await _children(db, user)
    if children:
        text += "\n<b>Farzandlaringiz o'qituvchilari:</b>\n"
        for child in children:
            text += f"• {esc(child['full_name'])} — {esc(child.get('teacher_name') or '—')}\n"
    text += "\nDars jadvali va boshqa savollar uchun administratorga yozing."
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard: list[list[InlineKeyboardButton]] = []
    if support:
        handle = support if support.startswith("@") else "@" + support
        keyboard.append([InlineKeyboardButton(text="💬 Adminga yozish", url=f"https://t.me/{handle.lstrip('@')}")])
    keyboard.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="home")])
    await ui.send(event, text, InlineKeyboardMarkup(inline_keyboard=keyboard))
