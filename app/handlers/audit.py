"""Audit jurnali va zaxira nusxa (superadmin)."""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit as write_audit
from app.utils import esc, fmt_datetime, safe_int
from config import settings

router = Router(name="audit")

PER_PAGE = 10


@router.message(F.text == "🛡 Audit")
async def audit_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    await _render(message, db, 1)


@router.callback_query(F.data.in_({"aud:menu", "aud:menu:1"}))
async def audit_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await _render(callback, db, 1)
    await callback.answer()


@router.callback_query(F.data.startswith("aud:menu:"))
async def audit_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 9999)
    await _render(callback, db, page)
    await callback.answer()


async def _render(event: Message | CallbackQuery, db: Database, page: int) -> None:
    total = int(await db.scalar("SELECT COUNT(*) FROM audit_log") or 0)
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(pages, page))
    offset = (page - 1) * PER_PAGE
    rows_data = await db.fetchall(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (PER_PAGE, offset),
    )
    text = f"🛡 <b>Audit jurnali</b>\n\nJami yozuv: <b>{total}</b> · Sahifa {page}/{pages}\n"
    if not rows_data:
        text += "\nHozircha yozuv yo'q."
    for row in rows_data:
        actor = row.get("actor_tg") or "—"
        target = ""
        if row.get("target_type"):
            target = f" → {row['target_type']}"
            if row.get("target_id"):
                target += f"#{row['target_id']}"
        text += (
            f"\n<b>#{row['id']}</b> · <code>{esc(row['action'])}</code>{esc(target)}"
            f"\n👤 <code>{esc(actor)}</code> · 🕒 {esc(fmt_datetime(row.get('created_at'), settings.tz))}"
        )
        if row.get("details"):
            text += f"\n<i>{esc(str(row['details'])[:150])}</i>"
        text += "\n"
    rows: list[list[tuple[str, str]]] = []
    if pages > 1:
        rows.append(kb.pager("aud:menu", page, pages))
    rows.append([("💾 Zaxira nusxa", "aud:backup")])
    rows.append([("🧹 Eskirgan yozuvlarni tozalash", "aud:clean")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.callback_query(F.data == "aud:clean")
async def audit_clean_prompt(callback: CallbackQuery, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin"):
        return
    await ui.send(
        callback,
        "🧹 <b>Audit tozalash</b>\n\n"
        "90 kundan eski audit yozuvlari o'chirilsinmi?\n"
        "Bu amal qaytarilmaydi. Joriy ma'lumotlarga tegmaydi.",
        kb.confirm_kb("aud:cleanyes", "aud:menu", "🧹 Ha, tozalash"),
    )
    await callback.answer()


@router.callback_query(F.data == "aud:cleanyes")
async def audit_clean(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin"):
        return
    cur = await db.execute(
        "DELETE FROM audit_log WHERE created_at < datetime('now', '-90 days')"
    )
    count = int(cur.rowcount or 0)
    await write_audit(db, user, "audit_clean", details={"deleted": count})
    await callback.answer(f"{count} ta yozuv o'chirildi", show_alert=True)
    await _render(callback, db, 1)


@router.callback_query(F.data == "aud:backup")
async def backup_now(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin"):
        return
    name = f"manual-{datetime.now(settings.tz).strftime('%Y%m%d-%H%M%S')}.db"
    target = settings.backup_dir / name
    try:
        await db.backup(target)
        ok = await db.integrity_ok()
    except Exception as exc:
        await callback.answer(f"Xato: {type(exc).__name__}", show_alert=True)
        return
    await write_audit(db, user, "backup_manual", details={"file": name, "integrity": ok})
    await callback.answer(
        f"✅ Zaxira yaratildi: {name}" + ("" if ok else " (integrity xato!)"),
        show_alert=True,
    )
