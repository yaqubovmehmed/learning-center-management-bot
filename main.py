"""Excellence LC boshqaruv boti — ishga tushirish nuqtasi."""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from app.bot import create_bot, create_dispatcher, setup_commands
from app.db import Database
from app.services import users
from app.worker import NotificationWorker, Scheduler
from config import BASE_DIR, settings

log = logging.getLogger("excellence")


def setup_logging() -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if root.handlers:
        return
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "bot.log", maxBytes=1_500_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    settings.validate()
    settings.prepare_dirs()

    db = Database(settings.db_path)
    await db.connect()
    bot = None
    worker_task: asyncio.Task | None = None
    scheduler_task: asyncio.Task | None = None
    try:
        if not await db.integrity_ok():
            log.error("Ma'lumotlar bazasi butunligi buzilgan! Zaxira nusxadan tiklang.")
            return
        await users.ensure_env_superadmins(db, settings.superadmin_ids)
        superadmins = await users.superadmin_count(db)
        if superadmins == 0 and not settings.bootstrap_code:
            log.error("Super admin yo'q va BOOTSTRAP_CODE berilmagan. Kirish imkonsiz.")
            return

        bot = create_bot(settings)
        me = await bot.get_me()
        username = me.username or ""
        if not username:
            log.warning("Bot username aniqlanmadi — taklif havolalari ishlamasligi mumkin.")
        dp = create_dispatcher(settings, db, username)
        await setup_commands(bot)

        worker_task = asyncio.create_task(NotificationWorker(bot, db).run(), name="outbox-worker")
        scheduler_task = asyncio.create_task(
            Scheduler(db, settings.tz, settings.backup_dir).run(), name="scheduler"
        )

        log.info("Bot ishga tushdi: @%s | DB: %s | superadmin: %s", username or "?", settings.db_path, superadmins)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
    finally:
        for task in (worker_task, scheduler_task):
            if task and not task.done():
                task.cancel()
        for task in (worker_task, scheduler_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
        await db.close()
        log.info("Bot to'xtatildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")
    except SystemExit:
        raise
    except Exception:
        logging.getLogger("excellence").exception("Kutilmagan xato")
        raise
