"""UI yordamchilari: xabar yuborish/tahrirlash, ruxsat tekshirish."""
from __future__ import annotations

import logging
from typing import Any, Sequence

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


async def send(
    event: Message | CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup | None = None,
    *,
    disable_preview: bool = True,
    edit: bool = True,
) -> Message | None:
    if isinstance(event, CallbackQuery):
        if edit and event.message:
            try:
                return await event.message.edit_text(
                    text,
                    reply_markup=kb,
                    disable_web_page_preview=disable_preview,
                )
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return event.message
                try:
                    return await event.message.answer(
                        text,
                        reply_markup=kb,
                        disable_web_page_preview=disable_preview,
                    )
                except Exception:
                    log.exception("Xabar yuborishda xato")
                    return None
        if event.message:
            return await event.message.answer(text, reply_markup=kb, disable_web_page_preview=disable_preview)
        return None
    return await event.answer(text, reply_markup=kb, disable_web_page_preview=disable_preview)


async def toast(event: CallbackQuery | Message, text: str, alert: bool = False) -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=alert)
        except Exception:
            pass
    else:
        await event.answer(text)


async def deny(event: Message | CallbackQuery, text: str = "⛔️ Sizda bu amal uchun ruxsat yo'q.") -> None:
    if isinstance(event, CallbackQuery):
        await toast(event, text, alert=True)
    else:
        await event.answer(text)


def has_role(user: dict[str, Any] | None, *roles: str) -> bool:
    return bool(user and user.get("role") in roles and int(user.get("is_active") or 0) == 1)


async def require(
    event: Message | CallbackQuery,
    user: dict[str, Any] | None,
    *roles: str,
    silent: bool = False,
) -> bool:
    if has_role(user, *roles):
        return True
    if not silent:
        if user is None:
            if isinstance(event, CallbackQuery):
                await toast(event, "Avval /start buyrug'ini bosing.", alert=True)
            else:
                await event.answer("Avval /start buyrug'ini bosing.")
        else:
            await deny(event)
    return False


async def require_private(event: CallbackQuery) -> bool:
    if event.message and event.message.chat.type == "private":
        return True
    await toast(event, "Faqat shaxsiy chatda ishlaydi.", alert=True)
    return False
