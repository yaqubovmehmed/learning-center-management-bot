"""Middleware: autentifikatsiya, rol, rate limit, private-chat himoyasi."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, Message, TelegramObject, Update

from app.security import limiter
from app.services import users

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    def __init__(self, db, superadmin_ids: tuple[int, ...]) -> None:
        self.db = db
        self.superadmin_ids = set(superadmin_ids)
        self._seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Faqat shaxsiy chatlarda ishlaymiz — guruhga tasodifan ma'lumot chiqmasin.
        if isinstance(event, Message) and event.chat.type != "private":
            return None
        if isinstance(event, CallbackQuery):
            if not event.message or event.message.chat.type != "private":
                await _safe_answer(event, "Bu amal faqat shaxsiy chatda ishlaydi.", True)
                return None

        tg_user = None
        if isinstance(event, Message):
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user
        elif isinstance(event, InlineQuery):
            tg_user = event.from_user

        if not tg_user:
            data["user"] = None
            return await handler(event, data)

        user = await users.by_tg(self.db, tg_user.id)
        if tg_user.id in self.superadmin_ids and (not user or user["role"] != "superadmin" or not user["is_active"]):
            await users.ensure_env_superadmins(self.db, (tg_user.id,))
            user = await users.by_tg(self.db, tg_user.id)

        if user and not int(user["is_active"]):
            if isinstance(event, CallbackQuery):
                await _safe_answer(event, "⛔️ Akkauntingiz faol emas. Administrator bilan bog'laning.", True)
            elif isinstance(event, Message):
                await event.answer("⛔️ Akkauntingiz faol emas. Administrator bilan bog'laning.")
            return None

        if user:
            now = time.monotonic()
            last = self._seen.get(int(user["id"]), 0.0)
            if now - last > 600:
                self._seen[int(user["id"])] = now
                await users.touch(self.db, int(user["id"]), tg_user.username)

        data["user"] = user
        data["tg_user"] = tg_user
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, msg_per_min: int, cb_per_min: int) -> None:
        self.msg_per_min = msg_per_min
        self.cb_per_min = cb_per_min

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        if not user:
            return await handler(event, data)
        tg_id = int(user["tg_id"])
        if isinstance(event, CallbackQuery):
            if not limiter.allow(tg_id, "cb", self.cb_per_min, 60.0):
                await _safe_answer(event, "⏳ Juda ko'p bosish. Bir oz kuting.", True)
                return None
        elif isinstance(event, Message):
            if not limiter.allow(tg_id, "msg", self.msg_per_min, 60.0):
                if limiter.should_notice(tg_id, 30.0):
                    await event.answer("⏳ Juda ko'p xabar yubordingiz. Bir daqiqadan keyin urinib ko'ring.")
                return None
        elif isinstance(event, InlineQuery):
            if not limiter.allow(tg_id, "inline", 20, 60.0):
                return None
        return await handler(event, data)


async def _safe_answer(cb: CallbackQuery, text: str, alert: bool = False) -> None:
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:
        pass
