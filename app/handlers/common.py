"""Umumiy handlerlar: /start, bosh menyu, yordam, /claim."""
from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit, constant_eq, limiter
from app.services import attendance, groups, invites, permissions, reports, settings as settings_service, students, teachers, tests, users
from app.states import LinkFlow
from app.utils import esc, fmt_date_long, fmt_phone, money, status_label, today_str
from config import settings

log = logging.getLogger(__name__)
router = Router(name="common")


def _line(label: str, value: str) -> str:
    return f"{label}: <b>{value}</b>"


async def dashboard_admin(db: Database, user: dict, tz) -> tuple[str, object]:
    data = await reports.dashboard(db, tz, float(await settings_service.get_int(db, "attendance_threshold", 75)))
    center = await settings_service.get(db, "center_name", "Excellence LC")
    today = today_str(tz)
    att = data["today"]
    rate = (att["attended"] / att["total"] * 100) if att["total"] else 0
    text = (
        f"🎓 <b>{esc(center)}</b> — boshqaruv paneli\n"
        f"📅 {esc(fmt_date_long(today))}\n\n"
        f"👥 O'quvchilar: <b>{data['students']}</b>"
        + (f" (muzlatilgan: {data['frozen']})" if data["frozen"] else "")
        + f"\n🗂 Patoklar: <b>{data['groups']}</b> · 👨‍🏫 O'qituvchilar: <b>{data['teachers']}</b>\n"
        f"✅ Bugungi davomat: <b>{att['attended']}/{att['total']}</b> ({rate:.0f}%)\n"
        f"❌ Kelmagan: <b>{att['absent']}</b> · ⏰ Kechikkan: <b>{att['late']}</b>\n\n"
        f"⚠️ E'tibor talab qiladi: <b>{data['risk_count']}</b> o'quvchi\n"
        f"📩 Yangi sabab xabarlari: <b>{data['new_reports']}</b>\n"
        f"🔔 Navbatdagi xabarlar: <b>{data['pending']}</b> · 📝 Shu oy testlari: <b>{data['month_tests']}</b>"
    )
    markup = kb.ikb([
        [("✅ Davomat", "att:menu"), ("📝 Testlar", "tst:menu")],
        [("📊 Hisobotlar", "rep:menu"), ("🔔 Xabarlar", "ntf:menu")],
        [("👥 O'quvchilar", "stu:l:1"), ("🗂 Patoklar", "grp:l:1")],
    ])
    return text, markup


async def dashboard_teacher(db: Database, user: dict, tz) -> tuple[str, object]:
    teacher = await permissions.teacher_profile(db, user)
    if not teacher:
        return "⛔️ O'qituvchi profili topilmadi. Administrator bilan bog'laning.", kb.ikb([kb.nav_row("home")])
    groups_list = await groups.list_groups(db, teacher_id=teacher["id"])
    student_count = await students.count_students(db, teacher_id=teacher["id"])
    today = today_str(tz)
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) AS attended, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id WHERE l.teacher_id=? AND l.date=?",
        (teacher["id"], today),
    ) or {}
    total = int(row.get("total") or 0)
    attended = int(row.get("attended") or 0)
    rate = (attended / total * 100) if total else 0
    text = (
        f"👨‍🏫 <b>{esc(teacher['name'])}</b> — o'qituvchi paneli\n"
        f"📅 {esc(fmt_date_long(today))}\n\n"
        f"🗂 Guruhlarim: <b>{len(groups_list)}</b> · 👥 O'quvchilar: <b>{student_count}</b>\n"
        f"✅ Bugungi davomat: <b>{attended}/{total}</b> ({rate:.0f}%)\n"
        f"❌ Kelmagan: <b>{int(row.get('absent') or 0)}</b>\n\n"
        f"Bugungi guruhlaringizni tanlab davomatni belgilang."
    )
    markup = kb.ikb([
        [("✅ Davomat", "att:menu"), ("📝 Testlar", "tst:menu")],
        [("🗂 Guruhlarim", "tch:groups"), ("👥 O'quvchilarim", "tch:students")],
    ])
    return text, markup


async def dashboard_parent(db: Database, user: dict, tz) -> tuple[str, object]:
    children = await students.children_of_user(db, int(user["id"]))
    today = date.fromisoformat(today_str(tz))
    start = today.replace(day=1).isoformat()
    lines = [f"👋 Assalomu alaykum, <b>{esc(user['full_name'])}</b>!\n"]
    if not children:
        lines.append("Hozircha farzandlaringiz ulanmagan. Markaz administratori bilan bog'laning.")
    else:
        lines.append("👶 <b>Farzandlaringiz:</b>\n")
        for child in children:
            att = await attendance.summary(db, int(child["id"]), start, today.isoformat())
            latest = await tests.latest_for_student(db, int(child["id"]), published_only=True)
            line = f"• <b>{esc(child['full_name'])}</b> — {esc(child.get('group_name') or 'guruhsiz')}"
            if att.get("rate") is not None:
                line += f"\n  ✅ Oy davomati: {att['rate']:.0f}%"
            if latest:
                percent = (float(latest["score"]) / float(latest["max_score"]) * 100) if latest["max_score"] else 0
                line += f" · 📝 Oxirgi test: {percent:.0f}%"
            lines.append(line)
    text = "\n".join(lines)
    rows: list[list[tuple[str, str]]] = []
    for child in children[:6]:
        rows.append([(f"👶 {child['full_name']}"[:55], f"par:child:{child['id']}")])
    rows.append([("📊 Natijalar", "par:results"), ("✅ Davomat", "par:attendance")])
    rows.append([("🔔 Sozlamalar", "par:settings"), ("☎️ Bog'lanish", "par:contact")])
    return text, kb.ikb(rows)


async def show_home(event: Message | CallbackQuery, db: Database, user: dict, tz) -> None:
    if user["role"] in permissions.ADMIN_ROLES:
        text, markup = await dashboard_admin(db, user, tz)
    elif user["role"] == "teacher":
        text, markup = await dashboard_teacher(db, user, tz)
    else:
        text, markup = await dashboard_parent(db, user, tz)
    await ui.send(event, text, markup)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    user: dict | None,
    bot: Bot,
) -> None:
    args = (command.args or "").strip()
    if args.startswith(("p_", "t_")):
        role = "parent" if args.startswith("p_") else "teacher"
        token = args[2:]
        if len(token) < 20:
            await message.answer("❌ Havola noto'g'ri.")
            return
        invite = await invites.find_valid(db, token=token, role=role, pepper=settings.pepper)
        if not invite:
            await message.answer(
                "❌ Havola yaroqsiz yoki muddati tugagan.\n"
                "Administratordan yangi havola so'rang."
            )
            return
        await state.clear()
        await state.set_state(LinkFlow.phone)
        await state.update_data(link_token=token, link_role=role)
        await audit(db, user, "invite_open", role, invite["target_id"])
        await message.answer(
            "🔐 <b>Xavfsizlik tasdiqlash</b>\n\n"
            "Akkauntni bog'lash uchun telefon raqamingizni tasdiqlang. "
            "Bu ma'lumot faqat markazda saqlangan raqam bilan solishtiriladi.\n\n"
            "Pastdagi tugma orqali raqamingizni ulashing.",
            reply_markup=kb.phone_request_kb(),
        )
        return

    await state.clear()
    if not user:
        count = await users.superadmin_count(db)
        if settings.bootstrap_code and count == 0:
            await message.answer(
                "🔐 <b>Birinchi ishga tushirish</b>\n\n"
                "Super admin sifatida ulanish uchun:\n"
                "<code>/claim KOD</code>\n\n"
                "Kod .env faylidagi BOOTSTRAP_CODE qiymati."
            )
        else:
            await message.answer(
                "⛔️ <b>Ruxsat yo'q</b>\n\n"
                "Bu bot faqat markaz xodimlari va ota-onalar uchun.\n"
                "Agar sizga kirish kerak bo'lsa, markaz administratoridan "
                "bir martalik taklif havolasini so'rang."
            )
        return

    if user["role"] == "teacher" and not await permissions.teacher_profile(db, user):
        await message.answer("⛔️ O'qituvchi profili faol emas. Administrator bilan bog'laning.")
        return

    await audit(db, user, "login")
    await show_home(message, db, user, settings.tz)
    await message.answer(
        "Menyu yangilandi. Kerakli bo'limni tanlang.",
        reply_markup=kb.main_menu(user["role"]),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    await state.clear()
    if not await ui.require(message, user, "superadmin", "admin", "teacher", "parent"):
        return
    await show_home(message, db, user, settings.tz)
    await message.answer("Kerakli bo'limni tanlang.", reply_markup=kb.main_menu(user["role"]))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    await state.clear()
    if not await ui.require(message, user, "superadmin", "admin", "teacher", "parent"):
        return
    await message.answer("Bekor qilindi.", reply_markup=kb.main_menu(user["role"]))
    await show_home(message, db, user, settings.tz)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, user: dict | None) -> None:
    if not user:
        await message.answer(f"🆔 Telegram ID: <code>{message.from_user.id}</code>\nRol: yo'q")
        return
    await message.answer(
        f"🆔 Telegram ID: <code>{user['tg_id']}</code>\n"
        f"👤 Ism: <b>{esc(user['full_name'])}</b>\n"
        f"🎭 Rol: <b>{user['role']}</b>\n"
        f"📅 Ro'yxatdan o'tgan: {esc(str(user['created_at'])[:10])}"
    )


@router.message(Command("claim"))
async def cmd_claim(message: Message, command: CommandObject, db: Database, user: dict | None) -> None:
    code = (command.args or "").strip()
    if not settings.bootstrap_code:
        await message.answer("❌ Boshlang'ich kod sozlanmagan.")
        return
    if not limiter.allow(message.from_user.id, "claim", 5, 600):
        await message.answer("⏳ Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")
        return
    if await users.superadmin_count(db) > 0:
        await message.answer("❌ Super admin allaqachon mavjud. Bu usul yopilgan.")
        return
    if not code or not constant_eq(code, settings.bootstrap_code):
        await audit(db, user, "claim_failed", details={"tg_id": message.from_user.id})
        await message.answer("❌ Kod noto'g'ri.")
        return
    if user:
        await users.set_role(db, int(user["id"]), "superadmin")
        await users.set_active(db, int(user["id"]), True)
    else:
        await users.create_user(
            db,
            tg_id=message.from_user.id,
            role="superadmin",
            full_name=message.from_user.full_name or "Superadmin",
            username=message.from_user.username,
        )
    user = await users.by_tg(db, message.from_user.id)
    await audit(db, user, "bootstrap_superadmin", "user", user["id"] if user else None)
    log.warning("Yangi super admin bootstrap orqali qo'shildi: %s", message.from_user.id)
    await message.answer(
        "✅ <b>Super admin</b> sifatida ulandingiz.\n"
        "Xavfsizlik uchun BOOTSTRAP_CODE ni .env faylidan olib tashlang va botni qayta ishga tushiring.",
    )
    if user:
        await show_home(message, db, user, settings.tz)
        await message.answer("Menyu tayyor.", reply_markup=kb.main_menu(user["role"]))


@router.message(Command("help"))
async def cmd_help(message: Message, user: dict | None) -> None:
    if not user:
        await message.answer("Yordam uchun /start buyrug'ini bosing.")
        return
    if user["role"] in permissions.ADMIN_ROLES:
        text = (
            "ℹ️ <b>Admin yordam</b>\n\n"
            "👥 <b>O'quvchilar</b> — qo'shish, qidirish, guruhga o'tkazish, ota-ona biriktirish.\n"
            "🗂 <b>Patoklar</b> — guruh yaratish, o'qituvchi biriktirish, jadval.\n"
            "✅ <b>Davomat</b> — guruh va kun bo'yicha keldi/kelmadi, kechikish.\n"
            "📝 <b>Testlar</b> — test yaratish, ball kiritish, natijalarni ota-onaga yuborish.\n"
            "📊 <b>Hisobotlar</b> — davomat, test tahlili, xavf ostidagilar, CSV.\n"
            "🔔 <b>Xabarlar</b> — navbat, qayta yuborish, ommaviy xabar.\n"
            "🛡 <b>Audit</b> — barcha muhim amallar jurnali.\n\n"
            "Buyruqlar: /start /menu /cancel /whoami /help"
        )
    elif user["role"] == "teacher":
        text = (
            "ℹ️ <b>O'qituvchi yordam</b>\n\n"
            "🗂 Guruhlarim — biriktirilgan patoklar.\n"
            "✅ Davomat — o'quvchilarni belgilash, vaqtni qayd etish.\n"
            "📝 Testlar — ball kiritish va natijalarni e'lon qilish.\n"
            "👥 O'quvchilarim — o'z guruhlaringiz o'quvchilari.\n"
            "📊 Hisobot — guruh davomati va natijalari.\n\n"
            "Ota-ona raqamlari va boshqa guruh ma'lumotlari yopiq."
        )
    else:
        text = (
            "ℹ️ <b>Ota-ona yordam</b>\n\n"
            "👶 Farzandlarim — farzandingiz kartasi.\n"
            "✅ Davomat — oylik davomat tarixi.\n"
            "📊 Natijalar — test va mock natijalari, o'sish dinamikasi.\n"
            "✉️ Sabab yuborish — darsga kelmaslik sababini o'qituvchiga yuborish.\n"
            "🔔 Sozlamalar — qaysi xabarlarni olishni tanlash.\n\n"
            "Muammo bo'lsa markaz administratoriga murojaat qiling."
        )
    await message.answer(text, reply_markup=kb.main_menu(user["role"]))


@router.message(F.text == "☎️ Yordam")
async def teacher_help(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "teacher"):
        return
    teacher = await permissions.teacher_profile(db, user)
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    text = (
        f"☎️ <b>Yordam</b>\n\n"
        f"🏫 {esc(center)}\n"
        f"👨‍🏫 O'qituvchi: <b>{esc(teacher['name'] if teacher else user['full_name'])}</b>\n\n"
        "Savol yoki muammo bo'lsa markaz administratoriga murojaat qiling."
    )
    rows: list[list[tuple[str, str]]] = []
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    buttons: list[list[InlineKeyboardButton]] = []
    if support:
        handle = support if support.startswith("@") else "@" + support
        text += f"\n☎️ Administrator: {esc(handle)}"
        buttons.append([InlineKeyboardButton(text="💬 Adminga yozish", url=f"https://t.me/{handle.lstrip('@')}")])
    rows.append(kb.nav_row("home"))
    for row in kb.ikb(rows).inline_keyboard:
        buttons.append(list(row))
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    await state.clear()
    if not await ui.require(callback, user, "superadmin", "admin", "teacher", "parent"):
        return
    await show_home(callback, db, user, settings.tz)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "deny")
async def cb_deny(callback: CallbackQuery) -> None:
    await callback.answer("⛔️ Ruxsat yo'q", show_alert=True)


@router.my_chat_member()
async def bot_added_to_chat(event: ChatMemberUpdated, bot: Bot) -> None:
    """Xavfsizlik: botni guruhga qo'shsa, darhol chiqib ketadi."""
    if event.chat.type == "private":
        return
    try:
        await bot.leave_chat(event.chat.id)
    except Exception:
        log.warning("Guruhdan chiqish imkoni bo'lmadi: %s", event.chat.id)


@router.message()
async def fallback(message: Message, user: dict | None, state: FSMContext) -> None:
    if not user:
        return
    current = await state.get_state()
    if current:
        await message.answer("Jarayon davom etmoqda. Bekor qilish uchun /cancel yuboring.")
        return
    await message.answer(
        "Men sizni tushunmadim. Iltimos, menyudagi tugmalardan foydalaning.",
        reply_markup=kb.main_menu(user["role"]),
    )
