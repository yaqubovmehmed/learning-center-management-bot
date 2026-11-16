"""Xavfsiz inline rejim: faqat guruh jadvali va kurs ma'lumoti.

O'quvchi, ota-ona, telefon yoki natija ma'lumotlari bu yerda ko'rsatilmaydi.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from app.db import Database
from app.services import groups, settings as settings_service
from app.utils import esc, format_days
from config import settings

router = Router(name="inline")


def _group_text(group: dict) -> str:
    center = group.get("_center") or "Excellence LC"
    text = (
        f"🗂 <b>{esc(group['name'])}</b>\n"
        f"🏫 {esc(center)}\n\n"
    )
    if group.get("course") or group.get("level"):
        text += f"📚 {esc(group.get('course') or '—')} · {esc(group.get('level') or '—')}\n"
    if group.get("teacher_name"):
        text += f"👨‍🏫 {esc(group['teacher_name'])}\n"
    text += f"📅 {esc(format_days(group.get('days')))}\n"
    if group.get("time"):
        text += f"🕒 {esc(group['time'])}"
        if group.get("duration_min"):
            text += f" · ⏱ {group['duration_min']} daq"
        text += "\n"
    if group.get("room"):
        text += f"🚪 {esc(group['room'])}\n"
    text += "\nℹ️ Batafsil ma'lumot uchun markaz administratoriga murojaat qiling."
    return text


@router.inline_query()
async def inline_groups(query: InlineQuery, db: Database) -> None:
    if not await settings_service.get_bool(db, "inline_public", True):
        await query.answer([], cache_time=5, is_personal=True)
        return
    term = (query.query or "").strip()[:40].lower()
    items = await groups.list_groups(db, include_archived=False, limit=100)
    if term:
        filtered = [
            g for g in items
            if term in (g.get("name") or "").lower()
            or term in (g.get("course") or "").lower()
            or term in (g.get("level") or "").lower()
            or term in (g.get("teacher_name") or "").lower()
        ]
    else:
        filtered = items
    filtered = filtered[:20]
    center = await settings_service.get(db, "center_name", "Excellence LC")
    results: list[InlineQueryResultArticle] = []
    for group in filtered:
        group = dict(group)
        group["_center"] = center
        title = group["name"]
        description_parts = [
            group.get("course") or "",
            group.get("level") or "",
            format_days(group.get("days")) if group.get("days") else "",
            group.get("time") or "",
        ]
        description = " · ".join(part for part in description_parts if part) or "Jadval mavjud emas"
        results.append(
            InlineQueryResultArticle(
                id=f"g{group['id']}",
                title=title[:90],
                description=description[:120],
                input_message_content=InputTextMessageContent(
                    message_text=_group_text(group),
                    parse_mode="HTML",
                ),
            )
        )
    if not results:
        results.append(
            InlineQueryResultArticle(
                id="empty",
                title="Guruh topilmadi",
                description="Boshqa nom yoki kurs bilan qidirib ko'ring.",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"🏫 <b>{esc(center)}</b>\n\n"
                        "So'rovingiz bo'yicha faol guruh topilmadi.\n"
                        "Administrator bilan bog'laning."
                    ),
                    parse_mode="HTML",
                ),
            )
        )
    await query.answer(results, cache_time=30, is_personal=True)
