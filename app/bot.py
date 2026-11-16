"""Bot va dispatcher yig'ilishi."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, ErrorEvent

from app.db import Database
from app.handlers import attendance, audit as audit_handlers, common, groups, inline, invite_admin, invites
from app.handlers import notifications, parents, reports, settings as settings_handlers, students, teachers, tests
from app.middlewares import AuthMiddleware, RateLimitMiddleware
from config import Settings

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Boshlash / bosh menyu"),
    BotCommand(command="menu", description="Asosiy menyu"),
    BotCommand(command="help", description="Yordam"),
    BotCommand(command="cancel", description="Amalni bekor qilish"),
    BotCommand(command="whoami", description="Mening ID va rolim"),
]


def create_bot(cfg: Settings) -> Bot:
    return Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )


def create_dispatcher(cfg: Settings, db: Database, bot_username: str) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["bot_username"] = bot_username
    dp["config"] = cfg

    auth = AuthMiddleware(db, cfg.superadmin_ids)
    limiter_mw = RateLimitMiddleware(cfg.rate_msg_per_min, cfg.rate_callback_per_min)
    for observer in (dp.message, dp.callback_query, dp.inline_query):
        observer.outer_middleware(auth)
        observer.outer_middleware(limiter_mw)

    # Tartib muhim: common router oxirida (catch-all fallback bor).
    for module in (
        invites,
        invite_admin,
        settings_handlers,
        audit_handlers,
        notifications,
        groups,
        students,
        attendance,
        tests,
        teachers,
        parents,
        reports,
        inline,
        common,
    ):
        dp.include_router(module.router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        update = event.update
        kind = update.event_type if update else "unknown"
        log.exception("Update xatosi (%s): %s", kind, type(event.exception).__name__)
        return True

    return dp


async def setup_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
    except Exception:
        log.warning("Buyruqlar menyusini o'rnatib bo'lmadi", exc_info=True)
