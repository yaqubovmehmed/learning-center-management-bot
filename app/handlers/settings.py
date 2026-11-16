"""Markaz sozlamalari va xabar parametrlari."""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import settings as settings_service
from app.states import SettingsEdit
from app.utils import clean_text, esc
from app.utils import WEEKDAYS_UZ

router = Router(name="settings")

TOGGLES = {
    "auto_absence_notify": "🔔 Kelmaganida avtomatik xabar",
    "auto_result_notify": "📊 Test natijalarini avtomatik yuborish",
    "digest_enabled": "📅 Haftalik hisobot",
    "inline_public": "🌐 Inline rejimda jadval ko'rsatish",
}

TEXT_KEYS = {
    "center_name": ("🏫 Markaz nomi", "Markaz nomini kiriting (2-60 belgi):"),
    "support_username": ("☎️ Qo'llab-quvvatlash manzili", "Telegram username kiriting (masalan <code>excellence_admin</code>). Bo'sh qoldirish uchun <code>-</code> yuboring:"),
    "attendance_threshold": ("📊 Davomat me'yori (%)", "Davomat me'yorini foizda kiriting (0-100). Masalan <code>75</code>:"),
    "digest_hour": ("🕘 Haftalik hisobot soati", "Soatni kiriting (0-23). Masalan <code>9</code>:"),
}


async def _values(db: Database) -> dict[str, Any]:
    data = await settings_service.all_settings(db)
    return {
        "center_name": data.get("center_name", "Excellence LC"),
        "support_username": data.get("support_username", ""),
        "attendance_threshold": data.get("attendance_threshold", "75"),
        "digest_weekday": data.get("digest_weekday", "0"),
        "digest_hour": data.get("digest_hour", "9"),
        "auto_absence_notify": data.get("auto_absence_notify", "1") == "1",
        "auto_result_notify": data.get("auto_result_notify", "1") == "1",
        "digest_enabled": data.get("digest_enabled", "1") == "1",
        "inline_public": data.get("inline_public", "1") == "1",
    }


async def _render(event: Message | CallbackQuery, db: Database) -> None:
    values = await _values(db)
    weekday = WEEKDAYS_UZ.get(int(values["digest_weekday"]), "dushanba")
    support = values["support_username"] or "—"
    text = (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"🏫 Markaz: <b>{esc(values['center_name'])}</b>\n"
        f"☎️ Aloqa: <b>{esc(support)}</b>\n"
        f"📊 Davomat me'yori: <b>{esc(values['attendance_threshold'])}%</b>\n"
        f"📅 Haftalik hisobot: <b>{weekday}, {values['digest_hour']}:00</b>\n\n"
        "<b>Xabarlar:</b>\n"
    )
    rows: list[list[tuple[str, str]]] = []
    for key, label in TOGGLES.items():
        enabled = bool(values[key])
        text += f"{'✅' if enabled else '⬜️'} {label}\n"
        rows.append([(f"{'✅' if enabled else '⬜️'} {label}"[:58], f"set:t:{key}")])
    rows.append([("✏️ Markaz nomi", "set:e:center_name"), ("✏️ Aloqa", "set:e:support_username")])
    rows.append([("📊 Me'yor", "set:e:attendance_threshold"), ("🕘 Soat", "set:e:digest_hour")])
    day_buttons = [[(("✅ " if int(values["digest_weekday"]) == i else "") + name[:3].title(), f"set:wd:{i}") for i, name in enumerate(WEEKDAYS_UZ.values())]]
    rows.extend(day_buttons)
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(F.text == "⚙️ Sozlamalar")
async def settings_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    await _render(message, db)


@router.callback_query(F.data.in_({"set:menu", "set:refresh"}))
async def settings_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    await _render(callback, db)
    await callback.answer()


@router.callback_query(F.data.startswith("set:t:"))
async def settings_toggle(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    key = callback.data.split(":")[2]
    if key not in TOGGLES:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    current = await settings_service.get_bool(db, key, True)
    await settings_service.set_value(db, key, "0" if current else "1")
    await audit(db, user, "setting_toggle", "setting", key, {"value": not current})
    await callback.answer("O'chirildi" if current else "Yoqildi")
    await _render(callback, db)


@router.callback_query(F.data.startswith("set:wd:"))
async def settings_weekday(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    try:
        value = int(callback.data.split(":")[2])
    except ValueError:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    if not 0 <= value <= 6:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await settings_service.set_value(db, "digest_weekday", value)
    await audit(db, user, "setting_change", "setting", "digest_weekday", {"value": value})
    await callback.answer(f"{WEEKDAYS_UZ[value].title()} tanlandi")
    await _render(callback, db)


@router.callback_query(F.data.startswith("set:e:"))
async def settings_edit_start(callback: CallbackQuery, state: FSMContext, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    key = callback.data.split(":")[2]
    if key not in TEXT_KEYS:
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await state.clear()
    await state.set_state(SettingsEdit.value)
    await state.update_data(setting_key=key)
    await ui.send(callback, TEXT_KEYS[key][1], kb.ikb([kb.nav_row("set:menu")]))
    await callback.answer()


@router.message(SettingsEdit.value)
async def settings_edit_save(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin"):
        return
    data = await state.get_data()
    key = data.get("setting_key")
    if key not in TEXT_KEYS:
        await state.clear()
        return
    raw = clean_text(message.text or "", 80).strip()
    value: Any = None
    if key == "center_name":
        if not (2 <= len(raw) <= 60) or "http" in raw.lower() or "<" in raw or ">" in raw:
            await message.answer("❌ Nom 2-60 belgi, havola va maxsus belgilarsiz bo'lsin.")
            return
        value = raw
    elif key == "support_username":
        if raw in ("-", ""):
            value = ""
        else:
            username = raw.lstrip("@").strip()
            if not (4 <= len(username) <= 32) or not username.replace("_", "").isalnum():
                await message.answer("❌ Username noto'g'ri. Faqat harf, raqam va _ (4-32 belgi).")
                return
            value = username
    elif key == "attendance_threshold":
        try:
            number = int(raw)
        except ValueError:
            await message.answer("❌ Faqat butun son kiriting (0-100).")
            return
        if not 0 <= number <= 100:
            await message.answer("❌ 0 dan 100 gacha bo'lsin.")
            return
        value = number
    elif key == "digest_hour":
        try:
            number = int(raw)
        except ValueError:
            await message.answer("❌ Faqat butun son kiriting (0-23).")
            return
        if not 0 <= number <= 23:
            await message.answer("❌ 0 dan 23 gacha bo'lsin.")
            return
        value = number
    if value is None:
        await state.clear()
        return
    await settings_service.set_value(db, key, value)
    await audit(db, user, "setting_change", "setting", key, {"value": value})
    await state.clear()
    await message.answer("✅ Saqlandi.")
    await _render(message, db)
