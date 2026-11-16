"""Admin uchun taklif havolasini yaratish va bekor qilish."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit, invite_url, teacher_invite_url
from app.services import invites
from app.utils import esc, safe_int
from config import settings

router = Router(name="invite_admin")


async def send_invite(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    *,
    role: str,
    target_id: int,
    bot_username: str,
) -> None:
    if role == "parent":
        target = await db.fetchone("SELECT * FROM parents WHERE id=?", (target_id,))
        if not target:
            await ui.toast(event, "Ota-ona topilmadi", True)
            return
        if target.get("user_id"):
            await ui.toast(event, "Bu ota-ona allaqachon Telegram bilan ulangan.", True)
            return
        if not target.get("phone"):
            await ui.toast(event, "Avval telefon raqamini kiriting.", True)
            return
        name = target["full_name"]
    else:
        target = await db.fetchone("SELECT * FROM teachers WHERE id=?", (target_id,))
        if not target:
            await ui.toast(event, "O'qituvchi topilmadi", True)
            return
        if target.get("user_id"):
            await ui.toast(event, "Bu o'qituvchi allaqachon Telegram bilan ulangan.", True)
            return
        if not target.get("phone"):
            await ui.toast(event, "Avval o'qituvchi telefon raqamini kiriting.", True)
            return
        if not target.get("is_active"):
            await ui.toast(event, "O'qituvchi faol emas.", True)
            return
        name = target["name"]

    token, invite_id = await invites.create_invite(
        db,
        role=role,
        target_id=target_id,
        created_by=int(user["id"]),
        pepper=settings.pepper,
    )
    url = (invite_url if role == "parent" else teacher_invite_url)(bot_username, token)
    await audit(db, user, "invite_create", role, target_id, {"invite_id": invite_id})
    subtitle = "ota-ona" if role == "parent" else "o'qituvchi"
    note = (
        "Havolani faqat kerakli shaxsga yuboring. U bir marta ishlaydi, 72 soat amal qiladi.\n"
        "Havolani ochgach, telefon raqamini tasdiqlash talab qilinadi."
    )
    await ui.send(
        event,
        f"🔗 <b>{esc(name)}</b> ({subtitle}) uchun taklif havolasi:\n\n"
        f"<code>{url}</code>\n\n"
        f"⏳ Amal qilish muddati: 72 soat\n{note}",
        kb.invite_kb(url, f"inv:revoke:{role}:{target_id}"),
    )


async def revoke_invite(event: Message | CallbackQuery, db: Database, user: dict, role: str, target_id: int) -> None:
    await invites.revoke_for_target(db, role, target_id)
    await audit(db, user, "invite_revoke", role, target_id)
    await ui.toast(event, "Havola bekor qilindi")


@router.callback_query(F.data.startswith("inv:revoke:"))
async def invite_revoke_callback(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    try:
        _, _, role, target_s = (callback.data or "").split(":")
    except ValueError:
        await callback.answer()
        return
    if role not in ("parent", "teacher"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    target_id = safe_int(target_s)
    if target_id <= 0:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await revoke_invite(callback, db, user, role, target_id)
    await callback.answer("Bekor qilindi")


@router.callback_query(F.data.startswith("inv:send:"))
async def invite_send_callback(
    callback: CallbackQuery,
    db: Database,
    user: dict | None,
    bot_username: str,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    try:
        _, _, role, target_s = (callback.data or "").split(":")
    except ValueError:
        await callback.answer()
        return
    if role not in ("parent", "teacher"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    target_id = safe_int(target_s)
    if target_id <= 0:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await send_invite(callback, db, user, role=role, target_id=target_id, bot_username=bot_username)
    await callback.answer()
