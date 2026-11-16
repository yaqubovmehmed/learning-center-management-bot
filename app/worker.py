"""Fon vazifalari: xabarlar navbati, haftalik hisobot, avtomatik backup."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.db import Database, utc_now
from app.services import notifications, settings as settings_service

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


class NotificationWorker:
    """Outbox'ni ketma-ket, Telegram limitlariga rioya qilib yuboradi."""

    def __init__(self, bot: Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    async def run(self) -> None:
        log.info("Xabarlar navbati ishga tushdi")
        while True:
            try:
                sent = await self.send_batch()
                if sent == 0:
                    await asyncio.sleep(1.5)
                else:
                    await asyncio.sleep(0.08)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Outbox worker xatosi")
                await asyncio.sleep(5)

    async def send_batch(self) -> int:
        rows = await self.db.fetchall(
            "SELECT * FROM outbox WHERE status='pending' AND next_try_at<=? ORDER BY id LIMIT 20",
            (utc_now(),),
        )
        for row in rows:
            await self._send(row)
            await asyncio.sleep(0.05)
        return len(rows)

    async def _send(self, row: dict) -> None:
        try:
            try:
                await self.bot.send_message(chat_id=int(row["recipient_tg"]), text=row["text"])
            except TelegramBadRequest:
                # Buzilgan HTML belgisi sabab bo'lsa, oddiy matn sifatida qayta yuboramiz.
                import html as _html
                import re as _re

                plain = _html.unescape(_re.sub(r"<[^>]+>", "", row["text"] or ""))
                await self.bot.send_message(
                    chat_id=int(row["recipient_tg"]), text=plain, parse_mode=None
                )
        except TelegramForbiddenError:
            await self.db.execute(
                "UPDATE outbox SET status='skipped', attempts=attempts+1, last_error='bot blocked', sent_at=? WHERE id=?",
                (utc_now(), row["id"]),
            )
            log.warning("Outbox %s: foydalanuvchi botni bloklagan", row["id"])
        except TelegramRetryAfter as exc:
            next_try = (datetime.now(timezone.utc) + timedelta(seconds=int(exc.retry_after) + 1)).strftime("%Y-%m-%d %H:%M:%S")
            await self.db.execute(
                "UPDATE outbox SET last_error=?, next_try_at=? WHERE id=?",
                ("rate limited", next_try, row["id"]),
            )
        except Exception as exc:
            attempts = int(row["attempts"]) + 1
            if attempts >= MAX_ATTEMPTS:
                await self.db.execute(
                    "UPDATE outbox SET status='failed', attempts=?, last_error=? WHERE id=?",
                    (attempts, str(exc)[:300], row["id"]),
                )
                log.error("Outbox %s yuborilmadi: %s", row["id"], type(exc).__name__)
            else:
                delay = min(300, 5 * (2 ** attempts))
                next_try = (datetime.now(timezone.utc) + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                await self.db.execute(
                    "UPDATE outbox SET attempts=?, last_error=?, next_try_at=? WHERE id=?",
                    (attempts, str(exc)[:300], next_try, row["id"]),
                )
        else:
            await self.db.execute(
                "UPDATE outbox SET status='sent', attempts=attempts+1, sent_at=?, last_error=NULL WHERE id=?",
                (utc_now(), row["id"]),
            )


class Scheduler:
    """Har daqiqada tekshiradi: haftalik digest, kunlik backup, limiter tozalash."""

    def __init__(self, db: Database, tz, backup_dir: Path) -> None:
        self.db = db
        self.tz = tz
        self.backup_dir = backup_dir
        self._last_cleanup = 0.0

    async def run(self) -> None:
        log.info("Rejalashtiruvchi ishga tushdi")
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Scheduler xatosi")
            await asyncio.sleep(30)

    async def tick(self) -> None:
        now = datetime.now(self.tz)
        today = now.date().isoformat()

        if await settings_service.get_bool(self.db, "digest_enabled", True):
            weekday = await settings_service.get_int(self.db, "digest_weekday", 0)
            hour = await settings_service.get_int(self.db, "digest_hour", 9)
            last = await settings_service.get(self.db, "last_digest_date", "")
            if now.weekday() == weekday and now.hour == hour and last != today:
                count = await notifications.queue_weekly_digests(self.db, self.tz)
                await settings_service.set_value(self.db, "last_digest_date", today)
                log.info("Haftalik digest navbatga qo'yildi: %s", count)

        if now.hour == 3:
            last_backup = await settings_service.get(self.db, "last_backup_date", "")
            if last_backup != today:
                await self.make_backup()
                await settings_service.set_value(self.db, "last_backup_date", today)

        # xotira tozalash (har 10 daqiqada)
        if now.minute % 10 == 0:
            from app.security import limiter

            limiter.cleanup()

    async def make_backup(self) -> Path | None:
        try:
            name = f"excellence-{datetime.now(self.tz).strftime('%Y%m%d')}.db"
            target = await self.db.backup(self.backup_dir / name)
            cutoff = date.today() - timedelta(days=14)
            for path in self.backup_dir.glob("excellence-*.db"):
                try:
                    stamp = path.stem.split("-")[-1]
                    if date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])) < cutoff:
                        path.unlink(missing_ok=True)
                except Exception:
                    continue
            log.info("Backup yaratildi: %s", name)
            return target
        except Exception:
            log.exception("Backup xatosi")
            return None
