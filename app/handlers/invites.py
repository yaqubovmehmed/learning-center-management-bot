"""Taklif havolasi orqali akkauntni xavfsiz bog'lash (telefon tasdiqlash)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit, limiter
from app.services import invites, teachers, users
from app.states import LinkFlow
from app.utils import normalize_phone
from config import settings

log = logging.getLogger(__name__)
router = Router(name="invites")


async def _expected_phone(db: Database, role: str, target_id: int) -> tuple[str | None, str | None]:
    """(telefon, xato)"""
    if role == "parent":
        row = await db.fetchone("SELECT phone FROM parents WHERE id=?", (target_id,))
    else:
        row = await db.fetchone("SELECT phone, is_active FROM teachers WHERE id=?", (target_id,))
    if not row:
        return None, "Profil topilmadi."
    if role == "teacher" and not int(row.get("is_active") or 0):
        return None, "O'qituvchi profili faol emas."
    if not row.get("phone"):
        return None, "Markazda telefon raqami saqlanmagan. Administrator bilan bog'laning."
    return row["phone"], None


async def _complete(
    message: Message,
    state: FSMContext,
    db: Database,
    *,
    role: str,
    token: str,
    tg_id: int,
    tg_name: str,
    username: str | None,
) -> None:
    await state.clear()
    invite = await invites.find_valid(db, token=token, role=role, pepper=settings.pepper)
    if not invite:
        await message.answer("❌ Havola muddati tugagan. Yangi havola so'rang.")
        return
    if role == "parent":
        record, error = await invites.bind_parent(
            db, invite=invite, tg_id=tg_id, tg_name=tg_name, username=username
        )
    else:
        record, error = await invites.bind_teacher(
            db, invite=invite, tg_id=tg_id, tg_name=tg_name, username=username
        )
    if error or not record:
        fallback = "Bog'lash amalga oshmadi."
        await message.answer(f"❌ {error or fallback}")
        await audit(db, None, "invite_bind_failed", role, invite["target_id"])
        return

    user = await users.by_tg(db, tg_id)
    await audit(db, user, "invite_consumed", role, invite["target_id"])
    if role == "parent":
        children = await db.fetchall(
            "SELECT s.full_name FROM student_parents sp JOIN students s ON s.id=sp.student_id WHERE sp.parent_id=?",
            (record["id"],),
        )
        names = ", ".join(c["full_name"] for c in children) or "—"
        await message.answer(
            "✅ <b>Akkaunt bog'landi!</b>\n\n"
            f"👤 {record['full_name']}\n"
            f"👶 Farzand(lar): <b>{names}</b>\n\n"
            "Endi davomat, test natijalari va haftalik hisobotlarni shu yerda olasiz.",
            reply_markup=kb.main_menu("parent"),
        )
    else:
        await message.answer(
            "✅ <b>O'qituvchi akkaunti bog'landi!</b>\n\n"
            f"👨‍🏫 {record['name']}\n\n"
            "Endi o'zingizga biriktirilgan guruhlarni boshqarasiz.",
            reply_markup=kb.main_menu("teacher"),
        )
    if user:
        from app.handlers.common import show_home

        await show_home(message, db, user, settings.tz)


async def _verify_and_answer(
    message: Message,
    state: FSMContext,
    db: Database,
    phone_raw: str | None,
) -> None:
    if not limiter.allow(message.from_user.id, "link_attempt", 6, 600):
        await message.answer("⏳ Juda ko'p urinish. 10 daqiqadan keyin qayta urinib ko'ring.")
        return
    data = await state.get_data()
    token = data.get("link_token")
    role = data.get("link_role")
    if not token or role not in ("parent", "teacher"):
        await state.clear()
        await message.answer("❌ Jarayon topilmadi. Havolani qaytadan oching.")
        return
    if not phone_raw:
        await message.answer("❌ Telefon raqam noto'g'ri. Format: +998 90 123 45 67")
        return
    phone = normalize_phone(phone_raw)
    if not phone:
        await message.answer("❌ Telefon raqam noto'g'ri. Format: +998 90 123 45 67")
        return
    invite = await invites.find_valid(db, token=token, role=role, pepper=settings.pepper)
    if not invite:
        await state.clear()
        await message.answer("❌ Havola muddati tugagan yoki bekor qilingan.")
        return
    expected, error = await _expected_phone(db, role, int(invite["target_id"]))
    if error:
        await state.clear()
        await message.answer(f"❌ {error}")
        return
    if expected != phone:
        await audit(db, None, "invite_phone_mismatch", role, invite["target_id"])
        await message.answer(
            "❌ Raqam markazdagi ma'lumotga mos kelmadi.\n"
            "Iltimos, markazda ro'yxatdan o'tgan raqamni yuboring yoki administrator bilan bog'laning."
        )
        return
    await _complete(
        message,
        state,
        db,
        role=role,
        token=token,
        tg_id=message.from_user.id,
        tg_name=message.from_user.full_name or "Foydalanuvchi",
        username=message.from_user.username,
    )


@router.message(LinkFlow.phone, F.contact)
async def link_contact(message: Message, state: FSMContext, db: Database) -> None:
    contact = message.contact
    if not contact or contact.user_id != message.from_user.id:
        await message.answer("❌ Faqat o'zingizning raqamingizni ulashingiz mumkin.")
        return
    await _verify_and_answer(message, state, db, contact.phone_number)


@router.message(LinkFlow.phone, F.text, ~F.text.startswith("/"))
async def link_phone_text(message: Message, state: FSMContext, db: Database) -> None:
    await _verify_and_answer(message, state, db, message.text)
