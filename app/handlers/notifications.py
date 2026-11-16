"""Xabarlar navbati, nosozliklar, sabab xabarlari va ommaviy xabar."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import attendance, notifications, permissions
from app.states import Broadcast
from app.utils import clean_text, esc, fmt_date, fmt_datetime, paginate, safe_int
from config import settings

router = Router(name="notifications")

AUDIENCES = {
    "parents": "👨‍👩‍👧 Barcha ota-onalarga",
    "teachers": "👨‍🏫 Barcha o'qituvchilarga",
    "all": "📢 Barcha faol foydalanuvchilarga",
}


def _esc_cb(text: str) -> str:
    return esc(text).replace("\n", " ")[:120]


async def _menu_text(db: Database) -> str:
    stat = await notifications.stats(db)
    new_reports = int(await db.scalar("SELECT COUNT(*) FROM absence_reports WHERE status='new'") or 0)
    return (
        "🔔 <b>Xabarlar markazi</b>\n\n"
        f"⏳ Navbatda: <b>{stat['pending']}</b>\n"
        f"✅ Yuborilgan: <b>{stat['sent']}</b>\n"
        f"⚠️ Nosoz: <b>{stat['failed']}</b>\n"
        f"🚫 Bloklangan: <b>{stat['skipped']}</b>\n\n"
        f"📩 Ko'rilmagan sabab xabarlari: <b>{new_reports}</b>\n\n"
        "Xabarlar fon rejimida ketma-ket yuboriladi."
    )


async def _menu_markup(db: Database) -> Any:
    new_reports = int(await db.scalar("SELECT COUNT(*) FROM absence_reports WHERE status='new'") or 0)
    rows: list[list[tuple[str, str]]] = [
        [("📩 Sabab xabarlari" + (f" ({new_reports})" if new_reports else ""), "ntf:reports:1")],
        [("⚠️ Nosoz xabarlar", "ntf:failed"), ("🔄 Qayta yuborish", "ntf:retry")],
        [("📢 Ommaviy xabar", "ntf:broadcast")],
        [("🔄 Yangilash", "ntf:menu")],
        kb.nav_row("home"),
    ]
    return kb.ikb(rows)


async def _show_menu(event: Message | CallbackQuery, db: Database) -> None:
    await ui.send(event, await _menu_text(db), await _menu_markup(db))


@router.message(F.text == "🔔 Xabarlar")
async def notifications_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    await _show_menu(message, db)


@router.callback_query(F.data == "ntf:menu")
async def notifications_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await _show_menu(callback, db)
    await callback.answer()


@router.callback_query(F.data == "ntf:failed")
async def failed_list(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    rows_data = await notifications.recent(db, "failed", 15)
    text = "⚠️ <b>Nosoz xabarlar</b> (oxirgi 15)\n"
    if not rows_data:
        text += "\nNosoz xabar yo'q."
    for row in rows_data:
        text += (
            f"\n• #{row['id']} → <code>{row['recipient_tg']}</code>"
            f"\n  {esc((row.get('last_error') or '—')[:120])}"
            f"\n  🕒 {esc(fmt_datetime(row.get('created_at'), settings.tz))}"
        )
    await ui.send(callback, text, kb.ikb([
        [("🔄 Hammasini qayta yuborish", "ntf:retry")],
        kb.nav_row("ntf:menu"),
    ]))
    await callback.answer()


@router.callback_query(F.data == "ntf:retry")
async def retry_failed(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    count = await notifications.retry_failed(db)
    await audit(db, user, "outbox_retry", details={"count": count})
    await callback.answer(f"{count} ta xabar navbatga qaytarildi", show_alert=True)
    await _show_menu(callback, db)


# ---------- Ota-ona sabab xabarlari ----------

@router.callback_query(F.data.startswith("ntf:reports:"))
async def absence_reports(
    callback: CallbackQuery,
    db: Database,
    user: dict | None,
    *,
    answer_cb: bool = True,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    items = await attendance.new_reports(db, 100)
    if not permissions.is_admin(user):
        teacher = await permissions.teacher_profile(db, user)
        if teacher:
            allowed = {
                int(r["student_id"])
                for r in await db.fetchall(
                    "SELECT s.id AS student_id FROM students s JOIN groups g ON g.id=s.group_id WHERE g.teacher_id=?",
                    (teacher["id"],),
                )
            }
            items = [i for i in items if int(i["student_id"]) in allowed]
        else:
            items = []
    chunk, page, pages, total = paginate(items, page, 8)
    text = f"📩 <b>Yangi sabab xabarlari</b>\n\nJami: <b>{total}</b>\n"
    if not items:
        text += "\nKo'rilmagan xabar yo'q."
    rows: list[list[tuple[str, str]]] = []
    for item in chunk:
        text += (
            f"\n• <b>{esc(item['student_name'])}</b> — {esc(item.get('group_name') or '—')}"
            f"\n  {esc((item.get('reason') or '')[:90])}"
            f"\n  📅 {esc(fmt_date(item.get('date')))}"
        )
        rows.append([(f"📩 {item['student_name']} · {fmt_date(item.get('date'))}"[:58], f"ntf:rep:{item['id']}")])
    if pages > 1:
        rows.append(kb.pager("ntf:reports", page, pages))
    rows.append(kb.nav_row("ntf:menu"))
    await ui.send(callback, text, kb.ikb(rows))
    if answer_cb:
        await callback.answer()


@router.callback_query(F.data.startswith("ntf:rep:"))
async def absence_report_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    report_id = safe_int(callback.data.split(":")[2])
    report = await db.fetchone(
        "SELECT ar.*, s.full_name AS student_name, g.name AS group_name, p.full_name AS parent_name, "
        "p.phone AS parent_phone FROM absence_reports ar "
        "JOIN students s ON s.id=ar.student_id LEFT JOIN groups g ON g.id=s.group_id "
        "LEFT JOIN parents p ON p.id=ar.parent_id WHERE ar.id=?",
        (report_id,),
    )
    if not report:
        await callback.answer("Topilmadi", show_alert=True)
        return
    if not await permissions.can_access_student(db, user, int(report["student_id"])):
        await ui.deny(callback)
        return
    status_label = "🆕 yangi" if report.get("status") == "new" else "✅ ko'rilgan"
    text = (
        f"📩 <b>Sabab xabari</b> #{report['id']}\n\n"
        f"👤 {esc(report['student_name'])}\n"
        f"🗂 {esc(report.get('group_name') or '—')}\n"
        f"📅 {esc(fmt_date(report.get('date')))}\n"
        f"🙋 {esc(report.get('parent_name') or '—')}\n\n"
        f"💬 {esc(report.get('reason') or '')}\n\n"
        f"Holat: {status_label}"
    )
    rows: list[list[tuple[str, str]]] = [[("👤 O'quvchi kartasi", f"stu:v:{report['student_id']}")]]
    if report.get("status") == "new":
        rows.insert(0, [("✅ Ko'rilgan deb belgilash", f"ntf:seen:{report['id']}")])
    rows.append(kb.nav_row("ntf:reports:1"))
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("ntf:seen:"))
async def absence_report_seen(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    report_id = safe_int(callback.data.split(":")[2])
    report = await db.fetchone("SELECT student_id FROM absence_reports WHERE id=?", (report_id,))
    if not report:
        await callback.answer("Topilmadi", show_alert=True)
        return
    if not await permissions.can_access_student(db, user, int(report["student_id"])):
        await ui.deny(callback)
        return
    await attendance.mark_report_seen(db, report_id)
    await audit(db, user, "absence_report_seen", "absence_report", report_id)
    await callback.answer("Ko'rilgan deb belgilandi")
    await absence_reports(callback, db, user, answer_cb=False)


# ---------- Ommaviy xabar ----------

@router.callback_query(F.data == "ntf:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await state.clear()
    await state.set_state(Broadcast.audience)
    rows = [[(label, f"ntf:b:{key}")] for key, label in AUDIENCES.items()]
    rows.append(kb.nav_row("ntf:menu"))
    await ui.send(
        callback,
        "📢 <b>Ommaviy xabar</b>\n\nKimga yuborilsin?",
        kb.ikb(rows),
    )
    await callback.answer()


@router.callback_query(Broadcast.audience, F.data.startswith("ntf:b:"))
async def broadcast_audience(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    audience = callback.data.split(":")[2]
    if audience not in AUDIENCES:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await state.update_data(audience=audience)
    await state.set_state(Broadcast.text)
    await ui.send(
        callback,
        "✍️ Xabar matnini kiriting (5-2000 belgi).\n\n"
        "Matn oddiy ko'rinishda yuboriladi. Havola va maxsus belgilar xavfsiz qayta ishlanadi.",
        kb.ikb([kb.nav_row("ntf:menu")]),
    )
    await callback.answer()


@router.message(Broadcast.text)
async def broadcast_text(message: Message, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    raw = (message.text or "").strip()
    if len(raw) < 5:
        await message.answer("❌ Xabar juda qisqa. Kamida 5 belgi kiriting.")
        return
    text = esc(clean_text(raw, 1800))
    data = await state.get_data()
    audience = data.get("audience") or "all"
    await state.update_data(text=text)
    await state.set_state(Broadcast.confirm)
    await message.answer(
        f"📢 <b>Tekshiring</b>\n\n"
        f"Kimga: <b>{esc(AUDIENCES.get(audience, audience))}</b>\n\n"
        f"———\n{text}\n———\n\n"
        "Yuborishni tasdiqlaysizmi?",
        reply_markup=kb.confirm_kb("ntf:bconfirm", "ntf:bcancel", "📢 Ha, yuborish"),
    )


@router.callback_query(Broadcast.confirm, F.data == "ntf:bconfirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    text = data.get("text") or ""
    audience = data.get("audience") or "all"
    if not text:
        await callback.answer("Matn yo'q", show_alert=True)
        return
    if audience == "parents":
        recipients = await db.fetchall(
            "SELECT tg_id FROM users WHERE role='parent' AND is_active=1"
        )
    elif audience == "teachers":
        recipients = await db.fetchall(
            "SELECT tg_id FROM users WHERE role='teacher' AND is_active=1"
        )
    else:
        recipients = await db.fetchall(
            "SELECT tg_id FROM users WHERE is_active=1 AND role IN ('parent','teacher','admin','superadmin')"
        )
    queued = 0
    for row in recipients:
        ok = await notifications.enqueue(
            db,
            kind="broadcast",
            recipient_tg=int(row["tg_id"]),
            text=text,
        )
        if ok:
            queued += 1
    await audit(db, user, "broadcast", details={"audience": audience, "queued": queued})
    await state.clear()
    await callback.answer(f"{queued} ta xabar navbatga qo'yildi", show_alert=True)
    await _show_menu(callback, db)


@router.callback_query(F.data == "ntf:bcancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await state.clear()
    await callback.answer("Bekor qilindi")
    await _show_menu(callback, db)
