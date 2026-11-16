"""Xabarlar navbati (outbox) va ota-onalarga yo'naltirish."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import Database, utc_now
from app.services import messages, reports, settings as settings_service, students
from app.utils import iso_week


async def enqueue(
    db: Database,
    *,
    kind: str,
    recipient_tg: int,
    text: str,
    dedupe_key: str | None = None,
    parent_id: int | None = None,
    student_id: int | None = None,
    delay_seconds: int = 0,
) -> bool:
    now = datetime.now(timezone.utc)
    next_try = (now + timedelta(seconds=max(0, delay_seconds))).strftime("%Y-%m-%d %H:%M:%S")
    cur = await db.execute(
        "INSERT OR IGNORE INTO outbox(kind, recipient_tg, parent_id, student_id, dedupe_key, text, created_at, next_try_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (kind, recipient_tg, parent_id, student_id, dedupe_key, text[:4096], utc_now(), next_try),
    )
    return (cur.rowcount or 0) > 0


_PREF_COLUMN = {"absent": "notif_absent", "late": "notif_late", "result": "notif_results"}


async def queue_to_parents(
    db: Database,
    *,
    student_id: int,
    kind: str,
    text: str,
    dedupe_base: str,
    student_name: str | None = None,
) -> dict[str, int]:
    pref = _PREF_COLUMN.get(kind)
    queued = 0
    unlinked = 0
    for parent in await students.parents_of_student(db, student_id):
        if not parent.get("tg_id") or not parent.get("user_active"):
            unlinked += 1
            continue
        if pref and not int(parent.get(pref) or 0):
            continue
        ok = await enqueue(
            db,
            kind=kind,
            recipient_tg=int(parent["tg_id"]),
            text=text,
            dedupe_key=f"{dedupe_base}:{parent['id']}",
            parent_id=int(parent["id"]),
            student_id=student_id,
        )
        if ok:
            queued += 1
    return {"queued": queued, "unlinked": unlinked}


async def queue_direct(
    db: Database,
    *,
    kind: str,
    tg_id: int,
    text: str,
    dedupe_key: str | None = None,
    student_id: int | None = None,
    parent_id: int | None = None,
) -> bool:
    return await enqueue(
        db,
        kind=kind,
        recipient_tg=tg_id,
        text=text,
        dedupe_key=dedupe_key,
        parent_id=parent_id,
        student_id=student_id,
    )


async def stats(db: Database) -> dict[str, int]:
    rows = await db.fetchall("SELECT status, COUNT(*) AS c FROM outbox GROUP BY status")
    data = {str(r["status"]): int(r["c"]) for r in rows}
    return {
        "pending": data.get("pending", 0),
        "sent": data.get("sent", 0),
        "failed": data.get("failed", 0),
        "skipped": data.get("skipped", 0),
    }


async def recent(db: Database, status: str = "failed", limit: int = 15) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT * FROM outbox WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
    )


async def retry_failed(db: Database) -> int:
    cur = await db.execute(
        "UPDATE outbox SET status='pending', attempts=0, last_error=NULL, next_try_at=? WHERE status='failed'",
        (utc_now(),),
    )
    return int(cur.rowcount or 0)


async def queue_weekly_digests(db: Database, tz) -> int:
    """Haftalik hisobotlarni navbatga qo'yadi. Takror yuborilmaydi."""
    if not await settings_service.get_bool(db, "digest_enabled", True):
        return 0
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    week = iso_week()
    parents = await db.fetchall(
        "SELECT p.*, u.tg_id FROM parents p JOIN users u ON u.id=p.user_id "
        "WHERE u.is_active=1 AND p.notif_weekly=1"
    )
    queued = 0
    for parent in parents:
        data = await reports.parent_digest_data(db, parent, tz)
        if not data:
            continue
        has_any = any((child.get("attendance") or {}).get("total") or child.get("latest_test") for child in data)
        if not has_any:
            continue
        text = messages.digest_message(
            parent_name=parent["full_name"],
            children=data,
            center_name=center,
            support=support,
        )
        if await enqueue(
            db,
            kind="digest",
            recipient_tg=int(parent["tg_id"]),
            text=text,
            dedupe_key=f"digest:{week}:{parent['id']}",
            parent_id=int(parent["id"]),
        ):
            queued += 1
    return queued
