"""O'qituvchilar boshqaruvi (faqat admin/superadmin)."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import groups, permissions, teachers, users
from app.states import TeacherAdd, TeacherEdit
from app.utils import clean_text, esc, fmt_phone, normalize_phone, paginate, safe_int, status_label, validate_name
from app.handlers.invite_admin import send_invite

router = Router(name="teachers")


async def show_teacher_list(event: Message | CallbackQuery, db: Database, user: dict, page: int = 1) -> None:
    items = await teachers.list_teachers(db, include_inactive=True)
    chunk, page, pages, total = paginate(items, page, 8)
    text = f"👨‍🏫 <b>O'qituvchilar</b>\n\nJami: <b>{total}</b>\n"
    rows: list[list[tuple[str, str]]] = []
    for teacher in chunk:
        icon = "🟢" if teacher["is_active"] else "⚪️"
        text += (
            f"\n{icon} <b>{esc(teacher['name'])}</b> — {teacher['groups_count']} guruh, "
            f"{teacher['students_count']} o'quvchi"
            + (" · ✅ Telegram" if teacher.get("tg_id") else " · ⚪️ ulanmagan")
        )
        rows.append([(f"{icon} {teacher['name']}"[:55], f"tch:v:{teacher['id']}")])
    if not items:
        text += "\nHozircha o'qituvchi yo'q."
    if pages > 1:
        rows.append(kb.pager("tch:l", page, pages))
    rows.append([("➕ Yangi o'qituvchi", "tch:add")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(F.text == "👨‍🏫 O'qituvchilar")
async def teachers_menu(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    await show_teacher_list(message, db, user)


@router.callback_query(F.data.startswith("tch:l:"))
async def teachers_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await show_teacher_list(callback, db, user, page)
    await callback.answer()


@router.callback_query(F.data.startswith("tch:v:"))
async def teacher_view(
    callback: CallbackQuery,
    db: Database,
    user: dict | None,
    *,
    answer_cb: bool = True,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    await show_teacher_card(callback, db, teacher_id, user)
    if answer_cb:
        await callback.answer()


async def show_teacher_card(event: Message | CallbackQuery, db: Database, teacher_id: int, user: dict) -> None:
    teacher = await teachers.get_teacher(db, teacher_id)
    if not teacher:
        await ui.toast(event, "Topilmadi", True)
        return
    text = (
        f"👨‍🏫 <b>{esc(teacher['name'])}</b>\n"
        f"{'🟢 Faol' if teacher['is_active'] else '⚪️ Faol emas'}\n\n"
        f"📞 Telefon: {esc(fmt_phone(teacher.get('phone')))}\n"
        f"📚 Fan: {esc(teacher.get('subject') or '—')}\n"
        f"💬 Telegram: {'✅ ulangan' if teacher.get('tg_id') else '⚪️ ulanmagan'}\n"
        f"🗂 Guruhlar: <b>{teacher['groups_count']}</b>\n"
        f"👥 O'quvchilar: <b>{teacher['students_count']}</b>\n"
        f"📅 Ishga qabul: {esc(teacher.get('hired_at') or '—')}"
    )
    if teacher.get("notes"):
        text += f"\n📝 {esc(teacher['notes'])}"
    groups_list = await groups.list_groups(db, teacher_id=teacher_id)
    rows: list[list[tuple[str, str]]] = []
    for group in groups_list[:6]:
        rows.append([(f"🗂 {group['name']} · {group['students_count']}"[:55], f"grp:v:{group['id']}")])
    if not teacher.get("tg_id"):
        rows.append([("🔗 Taklif havolasi", f"inv:send:teacher:{teacher_id}")])
    rows.append([("✏️ Tahrirlash", f"tch:edit:{teacher_id}")])
    if teacher["is_active"]:
        rows.append([("⛔️ Faolsizlantirish", f"tch:off:{teacher_id}")])
    else:
        rows.append([("♻️ Faollashtirish", f"tch:on:{teacher_id}")])
    if permissions.is_superadmin(user) and teacher.get("user_id") and teacher.get("user_active"):
        rows.append([("🛡 Admin qilish", f"tch:promote:{teacher_id}")])
    rows.append(kb.nav_row("tch:l:1"))
    await ui.send(event, text, kb.ikb(rows))


# ---------- Qo'shish ----------

@router.callback_query(F.data == "tch:add")
async def teacher_add_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await state.clear()
    await state.set_state(TeacherAdd.name)
    await ui.send(
        callback,
        "➕ <b>Yangi o'qituvchi</b>\n\n1/3 — To'liq ismni kiriting:",
        kb.ikb([kb.nav_row("tch:l:1")]),
    )
    await callback.answer()


@router.message(TeacherAdd.name)
async def teacher_add_name(message: Message, state: FSMContext) -> None:
    name = validate_name(message.text or "")
    if not name:
        await message.answer("❌ Ism noto'g'ri. 2-80 belgi.")
        return
    await state.update_data(name=name)
    await state.set_state(TeacherAdd.phone)
    await message.answer("2/3 — Telefon raqamini kiriting. Format: <code>+998 90 123 45 67</code>")


@router.message(TeacherAdd.phone)
async def teacher_add_phone(message: Message, state: FSMContext, db: Database) -> None:
    phone = normalize_phone(message.text or "")
    if not phone:
        await message.answer("❌ Telefon noto'g'ri.")
        return
    existing = await teachers.by_phone(db, phone)
    if existing:
        await message.answer(f"❌ Bu raqam <b>{esc(existing['name'])}</b> ga biriktirilgan.")
        return
    await state.update_data(phone=phone)
    await state.set_state(TeacherAdd.tg_id)
    await message.answer(
        "3/3 — O'qituvchining Telegram ID raqami (ixtiyoriy).\n"
        "Bilsangiz kiriting; aks holda taklif havolasi yaratiladi.",
        reply_markup=kb.skip_kb("tch:a:skip:tg", "tch:l:1"),
    )


async def _create_teacher(
    event: Message | CallbackQuery,
    state: FSMContext,
    db: Database,
    user: dict,
    tg_id: int | None,
    bot_username: str,
) -> None:
    data = await state.get_data()
    name = data.get("name")
    phone = data.get("phone")
    linked_user_id = None
    if tg_id:
        existing_user = await users.by_tg(db, tg_id)
        if existing_user:
            if existing_user["role"] in ("superadmin", "admin"):
                await ui.toast(event, "Bu Telegram akkaunt admin. O'qituvchi qilib bo'lmaydi.", True)
                return
            if existing_user["role"] == "parent":
                await ui.toast(event, "Bu Telegram akkaunt ota-ona sifatida ulangan.", True)
                return
            other = await db.fetchone(
                "SELECT name FROM teachers WHERE user_id=?", (existing_user["id"],)
            )
            if other:
                await ui.toast(event, f"Bu akkaunt {other['name']} ga ulangan.", True)
                return
            linked_user_id = int(existing_user["id"])
            await users.set_role(db, linked_user_id, "teacher")
            await users.set_active(db, linked_user_id, True)
        else:
            linked_user_id = await users.create_user(
                db,
                tg_id=tg_id,
                role="teacher",
                full_name=name,
                username=None,
                phone=phone,
            )
    teacher_id = await teachers.create_teacher(db, name=name, phone=phone, user_id=linked_user_id)
    await audit(db, user, "teacher_create", "teacher", teacher_id, {"name": name, "tg_linked": bool(tg_id)})
    await state.clear()
    await show_teacher_card(event, db, teacher_id, user)
    if isinstance(event, CallbackQuery):
        await event.answer("Qo'shildi")
    if not linked_user_id:
        await send_invite(event, db, user, role="teacher", target_id=teacher_id, bot_username=bot_username)


async def message_card(event: Message, db: Database, teacher: dict | None, user: dict) -> None:
    if not teacher:
        return
    text = (
        f"👨‍🏫 <b>{esc(teacher['name'])}</b> qo'shildi.\n\n"
        f"📞 {esc(fmt_phone(teacher.get('phone')))}\n"
        f"💬 Telegram: {'✅ ulangan' if teacher.get('tg_id') else '⚪️ havola kutilmoqda'}\n"
        f"🗂 Guruhlar: {teacher['groups_count']} · 👥 {teacher['students_count']}"
    )
    await event.answer(text, reply_markup=kb.ikb([[("👨‍🏫 O'qituvchi kartasi", f"tch:v:{teacher['id']}")], kb.nav_row("tch:l:1")]))


@router.message(TeacherAdd.tg_id)
async def teacher_add_tg(message: Message, state: FSMContext, db: Database, user: dict | None, bot_username: str) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or len(raw) < 5:
        await message.answer("❌ Telegram ID faqat raqamlardan iborat bo'lishi kerak.")
        return
    await _create_teacher(message, state, db, user, int(raw), bot_username)


@router.callback_query(TeacherAdd.tg_id, F.data == "tch:a:skip:tg")
async def teacher_add_skip_tg(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    user: dict | None,
    bot_username: str,
) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await _create_teacher(callback, state, db, user, None, bot_username)


# ---------- Tahrirlash ----------

@router.callback_query(F.data.startswith("tch:edit:"))
async def teacher_edit_menu(callback: CallbackQuery, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    await ui.send(
        callback,
        "✏️ <b>Qaysi maydonni tahrirlaysiz?</b>",
        kb.ikb([
            [("Ism", f"tch:ed:{teacher_id}:name"), ("Telefon", f"tch:ed:{teacher_id}:phone")],
            [("Fan", f"tch:ed:{teacher_id}:subject"), ("Izoh", f"tch:ed:{teacher_id}:notes")],
            kb.nav_row(f"tch:v:{teacher_id}"),
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tch:ed:"))
async def teacher_edit_field(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    _, _, teacher_id_s, field = callback.data.split(":")
    if field not in ("name", "phone", "subject", "notes"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await state.clear()
    await state.set_state(TeacherEdit.value)
    await state.update_data(teacher_id=safe_int(teacher_id_s), field=field)
    prompts = {
        "name": "Yangi ismni kiriting:",
        "phone": "Yangi telefon raqami:",
        "subject": "Fan yo'nalishi (masalan IELTS, General English):",
        "notes": "Izoh kiriting:",
    }
    await ui.send(callback, prompts[field], kb.ikb([kb.nav_row(f"tch:v:{teacher_id_s}")]))
    await callback.answer()


@router.message(TeacherEdit.value)
async def teacher_edit_value(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    teacher_id = int(data.get("teacher_id") or 0)
    field = data.get("field")
    raw = clean_text(message.text or "", 120)
    value: Any = raw
    if field == "name":
        value = validate_name(raw)
        if not value:
            await message.answer("❌ Ism noto'g'ri.")
            return
    elif field == "phone":
        value = normalize_phone(raw)
        if not value:
            await message.answer("❌ Telefon noto'g'ri.")
            return
        if await teachers.phone_taken(db, value, teacher_id):
            await message.answer("❌ Bu telefon boshqa o'qituvchida.")
            return
    elif field == "subject" and not raw:
        await message.answer("❌ Fan nomi bo'sh.")
        return
    await teachers.update_teacher(db, teacher_id, **{field: value})
    await state.clear()
    await audit(db, user, "teacher_edit", "teacher", teacher_id, {"field": field})
    await message.answer("✅ Saqlandi.")
    await show_teacher_card(message, db, teacher_id, user)


@router.callback_query(F.data.startswith("tch:off:"))
async def teacher_deactivate_prompt(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    teacher = await teachers.get_teacher(db, teacher_id)
    if not teacher:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await ui.send(
        callback,
        f"⛔️ <b>{esc(teacher['name'])}</b> faolsizlantirilsinmi?\n\n"
        "Telegram akkaunti bloklanadi, guruhlar tarixi saqlanadi. "
        "Guruhlarni boshqa o'qituvchiga o'tkazishni unutmang.",
        kb.confirm_kb(f"tch:offyes:{teacher_id}", f"tch:v:{teacher_id}", "⛔️ Ha, faolsizlantirish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tch:offyes:"))
async def teacher_deactivate(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    await teachers.set_active(db, teacher_id, False)
    await audit(db, user, "teacher_deactivate", "teacher", teacher_id)
    await callback.answer("Faolsizlantirildi")
    await teacher_view(callback, db, user, answer_cb=False)


@router.callback_query(F.data.startswith("tch:on:"))
async def teacher_activate(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    await teachers.set_active(db, teacher_id, True)
    await audit(db, user, "teacher_activate", "teacher", teacher_id)
    await callback.answer("Faollashtirildi")
    await teacher_view(callback, db, user, answer_cb=False)


@router.callback_query(F.data.startswith("tch:promote:"))
async def teacher_promote_prompt(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    teacher = await teachers.get_teacher(db, teacher_id)
    if not teacher or not teacher.get("user_id"):
        await callback.answer("Telegram ulanmagan", show_alert=True)
        return
    await ui.send(
        callback,
        f"🛡 <b>{esc(teacher['name'])}</b> admin qilinsinmi?\n\n"
        "Admin barcha o'quvchilar, guruhlar, moliyaviy sozlamalar va xabarlarni ko'radi. "
        "Bu katta vakolat — faqat ishonchli xodimga bering.",
        kb.confirm_kb(f"tch:promoteyes:{teacher_id}", f"tch:v:{teacher_id}", "🛡 Ha, admin qilish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tch:promoteyes:"))
async def teacher_promote(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin"):
        return
    teacher_id = safe_int(callback.data.split(":")[2])
    teacher = await teachers.get_teacher(db, teacher_id)
    if teacher and teacher.get("user_id"):
        await users.set_role(db, int(teacher["user_id"]), "admin")
        await audit(db, user, "teacher_promote_admin", "teacher", teacher_id)
        await callback.answer("Admin qilindi")
    else:
        await callback.answer("Telegram ulanmagan", show_alert=True)
        return
    await teacher_view(callback, db, user, answer_cb=False)
